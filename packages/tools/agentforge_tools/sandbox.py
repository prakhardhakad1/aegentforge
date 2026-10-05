"""CodeSandboxTool: run agent-generated Python in a restricted subprocess.

Security model (honest version -- see NOTES.md for the full discussion):

* Isolation boundary: a fresh ``python -I -c`` subprocess (isolated mode:
  ignores ``PYTHON*`` env vars and user site-packages config, does not prepend
  the current directory to ``sys.path``) running with ``cwd`` set to a fresh
  temporary directory. Wall-clock timeout kills runaway code.
* Network: blocked best-effort by a prelude injected ahead of the user code in
  the ``-c`` script. The prelude replaces ``socket.socket``,
  ``socket.create_connection``, ``socket.getaddrinfo`` and friends with
  functions that raise. Determined code (ctypes, C extensions) can bypass
  this -- it is a guardrail against accidental network use, NOT a security
  boundary against a motivated adversary.
* Memory: best-effort ``resource.setrlimit(RLIMIT_AS)`` applied inside the
  prelude when ``SANDBOX_MEMORY_MB`` is set. ``resource`` is POSIX-only, so
  **on Windows only the timeout and process isolation apply -- there is no
  hard memory cap**. The prelude swallows the ImportError and continues.
* Process spawning: ``os.system``/``os.popen``/``os.exec*``/``os.spawn*`` and
  ``subprocess.Popen/run/...`` are likewise monkeypatched to raise.
* Outputs: stdout/stderr are captured with size caps (default 100k chars
  each); any ``*.png`` written into the temp cwd is collected as an artifact
  and copied into the shared workspace when one is configured.

``ok`` semantics: ``ok=True`` means the sandbox itself completed a run (the
user code exiting non-zero is a *code* failure, reported via ``exit_code`` and
``stderr`` with ``data["error"]`` set). ``ok=False`` means the tool could not
complete (timeout, spawn failure, oversized input, internal error).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from agentforge_tools.base import Tool, ToolResult

__all__ = ["CodeSandboxTool", "SANDBOX_PRELUDE"]

DEFAULT_TIMEOUT_SECONDS = 20
HARD_MAX_TIMEOUT_SECONDS = 120
DEFAULT_MAX_OUTPUT_CHARS = 100_000
MAX_CODE_CHARS = 100_000

_ARTIFACT_GLOBS = ("*.png",)

# Injected ahead of user code inside `python -I -c "<prelude>\n<user code>"`.
# Everything is wrapped in try/except so a guard failure can never prevent
# user code from running; guards are best-effort by design.
SANDBOX_PRELUDE = r'''
import os as _af_os

# ---- memory cap (POSIX only, best-effort) --------------------------------
try:
    import resource as _af_resource
    _af_mb = _af_os.environ.get("SANDBOX_MEMORY_MB")
    if _af_mb:
        _af_limit = int(float(_af_mb) * 1024 * 1024)
        _af_resource.setrlimit(
            _af_resource.RLIMIT_AS, (_af_limit, _af_limit)
        )
except Exception:
    pass

# ---- guard function -------------------------------------------------------
def _af_blocked(*_af_args, **_af_kwargs):
    raise RuntimeError(
        "AgentForge sandbox: this operation (network/process access) "
        "is disabled inside the code sandbox"
    )

# ---- network block (best-effort) ------------------------------------------
try:
    import socket as _af_socket
    _af_socket.socket = _af_blocked
    _af_socket.create_connection = _af_blocked
    _af_socket.getaddrinfo = _af_blocked
    _af_socket.gethostbyname = _af_blocked
    _af_socket.gethostbyname_ex = _af_blocked
except Exception:
    pass

# ---- process-spawn block (best-effort) ------------------------------------
try:
    for _af_name in (
        "system", "popen", "execv", "execve", "execvp", "execvpe",
        "spawnv", "spawnve", "spawnvp", "fork", "forkpty",
    ):
        if hasattr(_af_os, _af_name):
            setattr(_af_os, _af_name, _af_blocked)
except Exception:
    pass
try:
    import subprocess as _af_subprocess
    _af_subprocess.Popen = _af_blocked
    _af_subprocess.run = _af_blocked
    _af_subprocess.call = _af_blocked
    _af_subprocess.check_call = _af_blocked
    _af_subprocess.check_output = _af_blocked
except Exception:
    pass

del _af_os
# ---- end of AgentForge prelude; user code follows ----
'''


class CodeSandboxTool(Tool):
    """Tool: execute a self-contained Python snippet in a restricted subprocess.

    The subprocess runs the same interpreter (``sys.executable``), so
    site-packages of the active venv (pandas, matplotlib, ...) are importable.
    Relative file writes land in the sandbox temp dir; PNGs are collected as
    artifacts (and copied into the workspace when one is configured).
    """

    name = "code_sandbox"
    description = (
        "Run a short self-contained Python snippet in a sandboxed subprocess "
        "to compute statistics, transform data or generate charts. No network "
        "access, no spawning processes, wall-clock timeout. Matplotlib is "
        "available (Agg backend): save figures as PNG files and they are "
        "returned as artifacts. Anything printed to stdout is captured."
    )
    parameters_json_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Complete Python source code to execute. Must be "
                    "self-contained (imports included). Write any output "
                    "files to the current working directory."
                ),
                "minLength": 1,
            },
            "timeout_seconds": {
                "type": "integer",
                "description": (
                    "Optional wall-clock timeout for this run, clamped to "
                    "[1, 120]. Defaults to env SANDBOX_TIMEOUT_SECONDS or 20."
                ),
            },
        },
        "required": ["code"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        """Create the sandbox tool.

        Args:
            workspace_dir: Optional shared workspace. When set, collected PNG
                artifacts are copied into
                ``<workspace>/artifacts/sandbox-<id>/`` so they outlive the
                temp dir.
        """
        self._workspace: Path | None = (
            Path(workspace_dir).resolve() if workspace_dir is not None else None
        )
        if self._workspace is not None:
            self._workspace.mkdir(parents=True, exist_ok=True)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _default_timeout() -> int:
        """Resolve the default timeout from env, falling back to 20s."""
        raw = os.environ.get("SANDBOX_TIMEOUT_SECONDS", "")
        try:
            value = int(float(raw))
            return max(1, value)
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_SECONDS

    @staticmethod
    def _max_output_chars() -> int:
        """Resolve the stdout/stderr char cap from env, default 100k."""
        raw = os.environ.get("SANDBOX_MAX_OUTPUT_CHARS", "")
        try:
            return max(1000, int(float(raw)))
        except (TypeError, ValueError):
            return DEFAULT_MAX_OUTPUT_CHARS

    @staticmethod
    def _decode_stream(raw: bytes | str | None) -> str:
        """Decode captured subprocess output (bytes or str or None) to text."""
        if raw is None:
            return ""
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    @staticmethod
    def _truncate(text: str, cap: int) -> tuple[str, bool]:
        """Cap ``text`` to ``cap`` chars; return (text, was_truncated)."""
        if len(text) <= cap:
            return text, False
        return text[:cap] + "\n...[output truncated by AgentForge sandbox]...", True

    def _collect_artifacts(self, tmpdir: Path) -> tuple[list[dict], list[str]]:
        """Glob PNGs from ``tmpdir``; copy them into the workspace if present.

        Returns:
            (artifacts, warnings) where artifacts are ``{name, path, kind}``
            dicts pointing at the *final* file locations and warnings hold
            non-fatal collection problems.
        """
        artifacts: list[dict] = []
        warnings: list[str] = []
        pngs = sorted(p for pattern in _ARTIFACT_GLOBS for p in tmpdir.glob(pattern))

        if not pngs:
            return artifacts, warnings

        if self._workspace is None:
            # No workspace configured: keep the temp dir alive and reference
            # artifacts in place. Caller (or OS temp cleanup) owns it later.
            return [
                {"name": p.name, "path": str(p), "kind": "file"}
                for p in pngs
            ], warnings

        dest_dir = self._workspace / "artifacts" / f"sandbox-{uuid.uuid4().hex[:8]}"
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            warnings.append(f"could not create artifact dir {dest_dir}: {exc}")
            return [], warnings

        for src in pngs:
            dest = dest_dir / src.name
            counter = 1
            while dest.exists():
                dest = dest_dir / f"{src.stem}_{counter}{src.suffix}"
                counter += 1
            try:
                shutil.copy2(src, dest)
            except OSError as exc:
                warnings.append(f"could not copy artifact {src.name}: {exc}")
                continue
            artifacts.append({"name": dest.name, "path": str(dest), "kind": "file"})
        return artifacts, warnings

    # -- tool entrypoint ------------------------------------------------------

    def run(self, inputs: dict) -> ToolResult:
        """Execute user code. Inputs: ``code`` (str), ``timeout_seconds`` (opt)."""
        code = inputs.get("code")
        if not isinstance(code, str) or not code.strip():
            return ToolResult(ok=False, error="code_sandbox requires non-empty 'code' string")
        if len(code) > MAX_CODE_CHARS:
            return ToolResult(
                ok=False,
                error=f"code too large: {len(code)} chars (limit {MAX_CODE_CHARS})",
            )

        raw_timeout = inputs.get("timeout_seconds")
        if raw_timeout is None:
            timeout = self._default_timeout()
        else:
            try:
                timeout = int(raw_timeout)
            except (TypeError, ValueError):
                return ToolResult(
                    ok=False, error=f"timeout_seconds must be an integer, got {raw_timeout!r}"
                )
        timeout = max(1, min(timeout, HARD_MAX_TIMEOUT_SECONDS))

        max_chars = self._max_output_chars()
        tmpdir = Path(tempfile.mkdtemp(prefix="agentforge_sandbox_"))
        script = SANDBOX_PRELUDE + "\n" + code

        env = os.environ.copy()
        env["MPLBACKEND"] = "Agg"  # headless matplotlib in the child
        env["MPLCONFIGDIR"] = str(tmpdir)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        cmd = [sys.executable, "-I", "-c", script]
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, isolated interpreter
                cmd,
                cwd=str(tmpdir),
                env=env,
                capture_output=True,
                text=False,
                timeout=timeout,
            )
            stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = self._decode_stream(exc.stdout)
            stderr = self._decode_stream(exc.stderr)
            exit_code = None
        except OSError as exc:
            # Spawn failure (missing interpreter, permissions, ...).
            shutil.rmtree(tmpdir, ignore_errors=True)
            return ToolResult(ok=False, error=f"sandbox failed to start interpreter: {exc}")
        duration_ms = int((time.monotonic() - started) * 1000)

        stdout, out_trunc = self._truncate(stdout, max_chars)
        stderr, err_trunc = self._truncate(stderr, max_chars)

        artifacts, warnings = self._collect_artifacts(tmpdir)
        if self._workspace is not None or not artifacts:
            shutil.rmtree(tmpdir, ignore_errors=True)

        data: dict = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "artifacts": artifacts,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
            "timeout_seconds": timeout,
            "stdout_truncated": out_trunc,
            "stderr_truncated": err_trunc,
        }
        if warnings:
            data["warnings"] = warnings

        if timed_out:
            return ToolResult(
                ok=False,
                data=data,
                error=f"sandbox timed out after {timeout}s and the process was killed",
            )
        if exit_code != 0:
            data["error"] = f"user code exited with non-zero status {exit_code}"
        return ToolResult(ok=True, data=data)
