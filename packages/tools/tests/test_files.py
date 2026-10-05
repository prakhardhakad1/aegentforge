"""Tests for FileTools: workspace scoping, traversal attacks, size caps."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_tools.files import FileTools, PathPolicyError, resolve_in_workspace


class TestResolveInWorkspace:
    """Direct unit tests for the path-resolution policy."""

    def test_relative_path_resolves_inside(self, workspace: Path) -> None:
        """A plain relative path resolves under the workspace root."""
        resolved = resolve_in_workspace(workspace, "data/file.csv")
        assert resolved.is_relative_to(workspace.resolve())
        assert resolved.name == "file.csv"

    def test_root_allowed_when_requested(self, workspace: Path) -> None:
        """Empty / '.' resolves to the workspace root only with allow_root."""
        assert resolve_in_workspace(workspace, ".", allow_root=True) == workspace.resolve()
        assert resolve_in_workspace(workspace, "", allow_root=True) == workspace.resolve()
        with pytest.raises(PathPolicyError):
            resolve_in_workspace(workspace, ".")

    def test_dotdot_rejected(self, workspace: Path) -> None:
        """'..' segments are rejected before resolution."""
        for attack in ("../escape.txt", "a/../../escape.txt", "..\\escape.txt"):
            with pytest.raises(PathPolicyError, match="\\.\\."):
                resolve_in_workspace(workspace, attack)

    def test_absolute_escape_rejected(self, workspace: Path) -> None:
        """Absolute paths outside the workspace are rejected."""
        with pytest.raises(PathPolicyError, match="escapes the workspace"):
            resolve_in_workspace(workspace, "C:/Windows/win.ini")

    def test_nul_byte_rejected(self, workspace: Path) -> None:
        """NUL bytes are rejected outright."""
        with pytest.raises(PathPolicyError, match="NUL"):
            resolve_in_workspace(workspace, "file\x00.txt")

    def test_non_string_rejected(self, workspace: Path) -> None:
        """Non-string paths are rejected."""
        with pytest.raises(PathPolicyError, match="must be a string"):
            resolve_in_workspace(workspace, 42)  # type: ignore[arg-type]


class TestFileToolsReadWriteList:
    """Happy paths for the three operations."""

    def test_write_read_roundtrip(self, workspace: Path) -> None:
        """Written content reads back byte-for-byte (well, str-for-str)."""
        tool = FileTools(workspace)
        write = tool.run({"operation": "write", "path": "notes/summary.md", "content": "# hi"})
        assert write.ok is True
        assert write.data is not None and write.data["bytes_written"] == len("# hi")

        read = tool.run({"operation": "read", "path": "notes/summary.md"})
        assert read.ok is True
        assert read.data is not None
        assert read.data["content"] == "# hi"
        assert read.data["size"] == len("# hi")
        assert Path(write.data["absolute_path"]).is_relative_to(workspace.resolve())

    def test_overwrite_is_atomic_swap(self, workspace: Path) -> None:
        """Rewriting a file replaces its content fully and leaves no temp files."""
        tool = FileTools(workspace)
        assert tool.run({"operation": "write", "path": "f.txt", "content": "one"}).ok
        assert tool.run({"operation": "write", "path": "f.txt", "content": "two"}).ok
        read = tool.run({"operation": "read", "path": "f.txt"})
        assert (read.data or {})["content"] == "two"
        listing = tool.run({"operation": "list", "path": ""})
        names = [e["path"] for e in (listing.data or {})["entries"]]
        assert not any(".tmp-" in n for n in names)

    def test_list_recurses_with_sizes(self, workspace: Path) -> None:
        """list walks the tree, reporting dirs, files and sizes."""
        tool = FileTools(workspace)
        tool.run({"operation": "write", "path": "a/b/c.txt", "content": "abc"})
        result = tool.run({"operation": "list"})
        assert result.ok is True
        entries = (result.data or {})["entries"]
        paths = {e["path"]: e for e in entries}
        assert paths["a"]["type"] == "dir"
        assert paths["a/b/c.txt"]["type"] == "file"
        assert paths["a/b/c.txt"]["size"] == 3

    def test_read_errors(self, workspace: Path) -> None:
        """Missing files and directories read as failures, not exceptions."""
        tool = FileTools(workspace)
        missing = tool.run({"operation": "read", "path": "nope.txt"})
        assert missing.ok is False and "not found" in (missing.error or "")

        (workspace / "dir").mkdir()
        result = tool.run({"operation": "read", "path": "dir"})
        assert result.ok is False and "directory" in (result.error or "")

    def test_write_requires_string_content(self, workspace: Path) -> None:
        """Non-string content is rejected."""
        tool = FileTools(workspace)
        result = tool.run({"operation": "write", "path": "f.bin", "content": b"bytes"})
        assert result.ok is False
        assert "string 'content'" in (result.error or "")

    def test_write_workspace_root_rejected(self, workspace: Path) -> None:
        """The workspace root itself is never writable."""
        tool = FileTools(workspace)
        result = tool.run({"operation": "write", "path": "", "content": "x"})
        assert result.ok is False

    def test_bad_operation(self, workspace: Path) -> None:
        """Unknown operations fail with a clear error."""
        tool = FileTools(workspace)
        result = tool.run({"operation": "delete", "path": "f.txt"})
        assert result.ok is False
        assert "read'|'write'|'list'" in (result.error or "")

    def test_missing_path_for_read_write(self, workspace: Path) -> None:
        """read/write without a path fails."""
        tool = FileTools(workspace)
        assert tool.run({"operation": "read"}).ok is False
        assert tool.run({"operation": "write", "content": "x"}).ok is False


class TestFileToolsTraversalDefense:
    """Attack attempts through the tool entrypoint must fail cleanly."""

    def test_parent_traversal_write(self, workspace: Path) -> None:
        """Writing outside via .. is rejected and nothing is created."""
        tool = FileTools(workspace)
        result = tool.run(
            {"operation": "write", "path": "../escaped.txt", "content": "evil"}
        )
        assert result.ok is False
        assert "rejected" in (result.error or "")
        assert not (workspace.parent / "escaped.txt").exists()

    def test_parent_traversal_read(self, workspace: Path) -> None:
        """Reading outside via .. is rejected."""
        tool = FileTools(workspace)
        result = tool.run({"operation": "read", "path": "../../secrets.txt"})
        assert result.ok is False
        assert "rejected" in (result.error or "")

    def test_absolute_path_read(self, workspace: Path) -> None:
        """Absolute paths cannot read host files."""
        tool = FileTools(workspace)
        result = tool.run({"operation": "read", "path": "C:/Windows/win.ini"})
        assert result.ok is False
        assert "escapes" in (result.error or "") or "rejected" in (result.error or "")

    def test_absolute_path_write(self, workspace: Path) -> None:
        """Absolute paths cannot write host files."""
        tool = FileTools(workspace)
        result = tool.run(
            {"operation": "write", "path": "C:/Users/Public/evil.txt", "content": "x"}
        )
        assert result.ok is False
        assert not Path("C:/Users/Public/evil.txt").exists()

    def test_nul_byte_path(self, workspace: Path) -> None:
        """NUL-byte paths are rejected through the tool too."""
        tool = FileTools(workspace)
        result = tool.run({"operation": "read", "path": "safe\x00.txt"})
        assert result.ok is False
        assert "NUL" in (result.error or "")

    def test_list_traversal(self, workspace: Path) -> None:
        """list cannot walk outside the workspace."""
        tool = FileTools(workspace)
        result = tool.run({"operation": "list", "path": ".."})
        assert result.ok is False
        assert "rejected" in (result.error or "")


class TestFileToolsCaps:
    """Size caps on read/write and entry caps on list."""

    def test_read_cap(self, workspace: Path) -> None:
        """Files larger than max_read_bytes are refused."""
        tool = FileTools(workspace, max_read_bytes=10)
        (workspace / "big.txt").write_text("y" * 100, encoding="utf-8")
        result = tool.run({"operation": "read", "path": "big.txt"})
        assert result.ok is False
        assert "too large" in (result.error or "")

    def test_write_cap(self, workspace: Path) -> None:
        """Content larger than max_write_bytes is refused."""
        tool = FileTools(workspace, max_write_bytes=10)
        result = tool.run({"operation": "write", "path": "big.txt", "content": "z" * 100})
        assert result.ok is False
        assert "too large" in (result.error or "")
        assert not (workspace / "big.txt").exists()

    def test_list_entry_cap(self, workspace: Path) -> None:
        """list truncates to max_list_entries and flags it."""
        tool = FileTools(workspace, max_list_entries=3)
        for i in range(10):
            (workspace / f"f{i}.txt").write_text("x", encoding="utf-8")
        result = tool.run({"operation": "list"})
        assert result.ok is True
        data = result.data or {}
        assert data["count"] == 3
        assert data["truncated"] is True
