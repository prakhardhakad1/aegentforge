"""Tests for CodeSandboxTool: subprocess isolation, timeout, guards, artifacts.

Every test spawns a real ``python -I -c`` child process (offline, no network):
the children only do local computation and file writes. On Windows the memory
rlimit branch is documented as unavailable, so the rlimit test is POSIX-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentforge_tools.sandbox import CodeSandboxTool, SANDBOX_PRELUDE


def _make_tool(workspace: Path | None = None) -> CodeSandboxTool:
    """Build a sandbox tool with an optional workspace."""
    return CodeSandboxTool(workspace_dir=workspace) if workspace else CodeSandboxTool()


class TestSandboxHappyPath:
    """Normal execution, stdout/stderr capture, output caps."""

    def test_prints_and_exit_zero(self, workspace: Path) -> None:
        """Simple arithmetic prints to stdout and exits 0."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "print(2 + 2)"})
        assert result.ok is True
        data = result.data or {}
        assert data["exit_code"] == 0
        assert data["stdout"].strip() == "4"
        assert data["stderr"] == ""
        assert data["timed_out"] is False
        assert data["artifacts"] == []
        assert data["duration_ms"] >= 0

    def test_stderr_capture(self, workspace: Path) -> None:
        """stderr is captured alongside stdout."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "import sys\nprint('out'); sys.stderr.write('err')"})
        assert result.ok is True
        data = result.data or {}
        assert data["stdout"].strip() == "out"
        assert data["stderr"].strip() == "err"

    def test_venv_site_packages_available(self, workspace: Path) -> None:
        """`python -I` still resolves the venv's site-packages (pandas import)."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "import pandas\nprint(pandas.__version__)"})
        assert result.ok is True
        assert (result.data or {})["exit_code"] == 0
        assert (result.data or {})["stdout"].strip()[0].isdigit()

    def test_workspace_relative_writes(self, workspace: Path) -> None:
        """cwd is the temp dir, so relative writes land there (and vanish)."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "open('notes.txt', 'w').write('hi')"})
        assert result.ok is True

    def test_output_size_cap(self, workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Huge stdout is truncated to the configured cap with a marker."""
        monkeypatch.setenv("SANDBOX_MAX_OUTPUT_CHARS", "2000")
        tool = _make_tool(workspace)
        result = tool.run({"code": "print('x' * 50_000)"})
        assert result.ok is True
        data = result.data or {}
        assert data["stdout_truncated"] is True
        assert len(data["stdout"]) < 2200
        assert "truncated by AgentForge sandbox" in data["stdout"]

    def test_input_validation(self, workspace: Path) -> None:
        """Missing, empty, oversized code and bad timeout fail without running."""
        tool = _make_tool(workspace)
        assert tool.run({}).ok is False
        assert tool.run({"code": "   "}).ok is False
        assert tool.run({"code": 123}).ok is False  # type: ignore[dict-item]
        assert tool.run({"code": "x" * 100_001}).ok is False
        bad_timeout = tool.run({"code": "print(1)", "timeout_seconds": "soon"})
        assert bad_timeout.ok is False
        assert "timeout_seconds" in (bad_timeout.error or "")

    def test_timeout_seconds_clamped(self, workspace: Path) -> None:
        """timeout_seconds is clamped to [1, 120] and echoed in data."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "print(1)", "timeout_seconds": 5000})
        assert result.ok is True
        assert (result.data or {})["timeout_seconds"] == 120


class TestSandboxFailures:
    """Code errors vs tool errors: the documented ok semantics."""

    def test_syntax_error_is_ok_true_with_exit_code(self, workspace: Path) -> None:
        """A syntax error is a *code* failure: ok=True, exit_code!=0, stderr."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "def broken(:\n    pass"})
        assert result.ok is True  # sandbox completed the run
        data = result.data or {}
        assert data["exit_code"] != 0
        assert "SyntaxError" in data["stderr"]
        assert "error" in data  # data["error"] explains the non-zero exit

    def test_runtime_error_is_ok_true_with_traceback(self, workspace: Path) -> None:
        """Runtime exceptions produce a traceback on stderr and non-zero exit."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "raise ValueError('nope')"})
        assert result.ok is True
        data = result.data or {}
        assert data["exit_code"] != 0
        assert "ValueError" in data["stderr"]
        assert "nope" in data["stderr"]

    def test_timeout_is_ok_false(self, workspace: Path) -> None:
        """Runaway code is killed at the wall clock: ok=False, timed_out=True."""
        tool = _make_tool(workspace)
        result = tool.run(
            {"code": "import time\ntime.sleep(30)", "timeout_seconds": 1}
        )
        assert result.ok is False
        data = result.data or {}
        assert data["timed_out"] is True
        assert data["exit_code"] is None
        assert "timed out" in (result.error or "")


class TestSandboxGuards:
    """Best-effort blocks for network and process spawning."""

    def test_socket_blocked(self, workspace: Path) -> None:
        """socket.socket raises inside the sandbox (guard, not security)."""
        tool = _make_tool(workspace)
        code = "import socket\nsocket.socket()\n"
        result = tool.run({"code": code})
        assert result.ok is True
        data = result.data or {}
        assert data["exit_code"] != 0
        assert "disabled inside the code sandbox" in data["stderr"]

    def test_create_connection_blocked(self, workspace: Path) -> None:
        """socket.create_connection is also blocked."""
        tool = _make_tool(workspace)
        result = tool.run(
            {"code": "import socket\nsocket.create_connection(('example.com', 80))"}
        )
        data = result.data or {}
        assert data["exit_code"] != 0
        assert "disabled inside the code sandbox" in data["stderr"]

    def test_subprocess_blocked(self, workspace: Path) -> None:
        """subprocess.run cannot spawn children from within the sandbox."""
        tool = _make_tool(workspace)
        result = tool.run(
            {"code": "import subprocess\nsubprocess.run(['echo', 'hi'])"}
        )
        data = result.data or {}
        assert data["exit_code"] != 0
        assert "disabled inside the code sandbox" in data["stderr"]

    def test_os_system_blocked(self, workspace: Path) -> None:
        """os.system / os.popen are blocked."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "import os\nos.system('echo hi')"})
        data = result.data or {}
        assert data["exit_code"] != 0
        assert "disabled inside the code sandbox" in data["stderr"]

    def test_guard_failure_cannot_break_user_code(self, workspace: Path) -> None:
        """The prelude is try/except wrapped: user code always runs."""
        tool = _make_tool(workspace)
        assert SANDBOX_PRELUDE.count("except Exception") >= 3
        result = tool.run({"code": "print('still alive')"})
        assert (result.data or {})["stdout"].strip() == "still alive"

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="resource.setrlimit is POSIX-only; Windows gets no hard memory cap",
    )
    def test_memory_limit_enforced_on_posix(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On POSIX, SANDBOX_MEMORY_MB becomes RLIMIT_AS inside the child."""
        monkeypatch.setenv("SANDBOX_MEMORY_MB", "512")
        tool = _make_tool(workspace)
        code = "x = 'y' * (4000 * 1024 * 1024)"  # 4 GB allocation
        result = tool.run({"code": code, "timeout_seconds": 30})
        data = result.data or {}
        assert data["exit_code"] != 0  # MemoryError kills it


class TestSandboxArtifacts:
    """PNG files written by user code are collected as artifacts."""

    def test_png_collected_and_copied_to_workspace(self, workspace: Path) -> None:
        """PNGs land under <workspace>/artifacts/sandbox-*/ and survive cleanup."""
        tool = _make_tool(workspace)
        code = (
            "open('chart.png', 'wb').write(b'\\x89PNG fake bytes')\n"
            "open('chart2.png', 'wb').write(b'\\x89PNG more')\n"
            "open('notes.txt', 'w').write('not an artifact')\n"
            "print('done')"
        )
        result = tool.run({"code": code})
        assert result.ok is True
        data = result.data or {}
        artifacts = data["artifacts"]
        assert [a["name"] for a in artifacts] == ["chart.png", "chart2.png"]
        for artifact in artifacts:
            assert artifact["kind"] == "file"
            path = Path(artifact["path"])
            assert path.exists() and path.stat().st_size > 0
            assert path.is_relative_to(workspace.resolve())

    def test_matplotlib_child_render(self, workspace: Path) -> None:
        """A real matplotlib figure renders headlessly inside the child."""
        tool = _make_tool(workspace)
        code = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "plt.figure()\n"
            "plt.plot([1, 2, 3], [2, 4, 9])\n"
            "plt.savefig('child.png')\n"
            "print('saved')"
        )
        result = tool.run({"code": code, "timeout_seconds": 45})
        assert result.ok is True, result.error
        data = result.data or {}
        assert data["exit_code"] == 0
        assert data["stdout"].strip() == "saved"
        names = [a["name"] for a in data["artifacts"]]
        assert "child.png" in names

    def test_non_png_files_not_collected(self, workspace: Path) -> None:
        """Only PNGs are treated as artifacts."""
        tool = _make_tool(workspace)
        result = tool.run({"code": "open('data.csv', 'w').write('a,b\\n1,2')"})
        assert (result.data or {})["artifacts"] == []
