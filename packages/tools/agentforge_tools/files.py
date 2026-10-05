"""Workspace-scoped file read/write/list tool with traversal protection.

All paths are resolved against a fixed workspace directory. The resolution
policy (``resolve_in_workspace``) is defense-in-depth:

1. Reject NUL bytes and empty paths outright.
2. Reject any path containing ``..`` segments *before* resolution (so logs and
   errors show the attack, not its neutralized form).
3. ``Path.resolve()`` the joined path (collapses symlinks and ``..`` that slip
   through exotic spellings) and require it to be ``is_relative_to`` the
   resolved workspace root. This defeats absolute escapes, drive-absolute
   Windows paths, and symlinked escapes.
"""

from __future__ import annotations

import os
from pathlib import Path

from agentforge_tools.base import Tool, ToolResult

__all__ = ["FileTools", "PathPolicyError", "resolve_in_workspace"]

DEFAULT_MAX_READ_BYTES = 1_000_000
DEFAULT_MAX_WRITE_BYTES = 2_000_000
DEFAULT_MAX_LIST_ENTRIES = 500


class PathPolicyError(ValueError):
    """Raised when a requested path violates the workspace policy."""


def resolve_in_workspace(workspace: Path, raw_path: str, *, allow_root: bool = False) -> Path:
    """Resolve ``raw_path`` inside ``workspace`` or raise :class:`PathPolicyError`.

    Args:
        workspace: The workspace root (will be resolved).
        raw_path: User/agent supplied path, absolute or relative.
        allow_root: When True, an empty string or ``.`` resolves to the
            workspace root itself (used by ``list``).

    Returns:
        The fully resolved absolute path guaranteed to be inside the workspace.

    Raises:
        PathPolicyError: On empty/NUL paths, ``..`` segments, or escapes.
    """
    if not isinstance(raw_path, str):
        raise PathPolicyError(f"path must be a string, got {type(raw_path).__name__}")
    if "\x00" in raw_path:
        raise PathPolicyError("path contains a NUL byte")
    stripped = raw_path.strip()
    if not stripped or stripped in (".", "./"):
        if allow_root:
            return Path(workspace).resolve()
        raise PathPolicyError("path must be a non-empty string")

    candidate = Path(stripped)
    if ".." in candidate.parts:
        raise PathPolicyError(f"path must not contain '..' segments: {raw_path!r}")

    workspace_resolved = Path(workspace).resolve()
    try:
        resolved = (workspace_resolved / candidate).resolve()
    except OSError as exc:  # pragma: no cover - platform edge cases
        raise PathPolicyError(f"path could not be resolved: {exc}") from exc

    if not resolved.is_relative_to(workspace_resolved):
        raise PathPolicyError(
            f"path escapes the workspace: {raw_path!r} -> {resolved}"
        )
    return resolved


class FileTools(Tool):
    """Tool: read / write / list files strictly inside the run workspace."""

    name = "files"
    description = (
        "Read, write, or list files inside this run's workspace directory. "
        "Paths are relative to the workspace root; escaping the workspace "
        "(absolute paths, '..' traversal, symlinks) is rejected. Use write to "
        "persist notes/CSVs, read to inspect them, list to discover files."
    )
    parameters_json_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "list"],
                "description": "Which file operation to perform.",
            },
            "path": {
                "type": "string",
                "description": (
                    "Workspace-relative path. Required for read/write; "
                    "optional for list (defaults to the workspace root)."
                ),
            },
            "content": {
                "type": "string",
                "description": "Text content to write (operation=write only).",
            },
        },
        "required": ["operation"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        workspace_dir: str | Path,
        max_read_bytes: int | None = None,
        max_write_bytes: int | None = None,
        max_list_entries: int | None = None,
    ) -> None:
        """Create file tools rooted at ``workspace_dir`` (created if missing).

        Caps default to env ``FILE_MAX_READ_BYTES`` / ``FILE_MAX_WRITE_BYTES``
        (or the module defaults) and may be overridden per-instance for tests.
        """
        self._workspace = Path(workspace_dir).resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)

        def _cap_from_env(env_name: str, default: int) -> int:
            raw = os.environ.get(env_name, "")
            try:
                return max(1, int(float(raw)))
            except (TypeError, ValueError):
                return default

        self._max_read = max_read_bytes or _cap_from_env(
            "FILE_MAX_READ_BYTES", DEFAULT_MAX_READ_BYTES
        )
        self._max_write = max_write_bytes or _cap_from_env(
            "FILE_MAX_WRITE_BYTES", DEFAULT_MAX_WRITE_BYTES
        )
        self._max_list = max_list_entries or DEFAULT_MAX_LIST_ENTRIES

    @property
    def workspace(self) -> Path:
        """The resolved workspace root."""
        return self._workspace

    # -- operations -----------------------------------------------------------

    def _read(self, path: str) -> ToolResult:
        try:
            resolved = resolve_in_workspace(self._workspace, path)
        except PathPolicyError as exc:
            return ToolResult(ok=False, error=f"read rejected: {exc}")
        if not resolved.exists():
            return ToolResult(ok=False, error=f"file not found: {path}")
        if resolved.is_dir():
            return ToolResult(ok=False, error=f"path is a directory, not a file: {path}")
        size = resolved.stat().st_size
        if size > self._max_read:
            return ToolResult(
                ok=False,
                error=(
                    f"file too large to read: {size} bytes "
                    f"(limit {self._max_read}); use csv_analyzer for datasets"
                ),
            )
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not read {path}: {exc}")
        return ToolResult(
            ok=True,
            data={
                "path": path,
                "absolute_path": str(resolved),
                "size": size,
                "content": content,
            },
        )

    def _write(self, path: str, content: object) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult(
                ok=False,
                error=f"write requires string 'content', got {type(content).__name__}",
            )
        if len(content.encode("utf-8", errors="replace")) > self._max_write:
            return ToolResult(
                ok=False,
                error=(
                    f"content too large to write: limit {self._max_write} bytes "
                    f"(env FILE_MAX_WRITE_BYTES)"
                ),
            )
        try:
            resolved = resolve_in_workspace(self._workspace, path)
        except PathPolicyError as exc:
            return ToolResult(ok=False, error=f"write rejected: {exc}")
        if resolved == self._workspace:
            return ToolResult(ok=False, error="refusing to write the workspace root itself")
        parent = resolved.parent
        if not parent.is_relative_to(self._workspace):
            return ToolResult(ok=False, error="write rejected: parent escapes workspace")
        try:
            parent.mkdir(parents=True, exist_ok=True)
            # 'x' would break legitimate overwrites; plain write_text with a
            # temp-file swap keeps writes atomic-ish and never partial.
            tmp_target = parent / f".{resolved.name}.tmp-{os.getpid()}"
            tmp_target.write_text(content, encoding="utf-8")
            os.replace(tmp_target, resolved)
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not write {path}: {exc}")
        return ToolResult(
            ok=True,
            data={
                "path": path,
                "absolute_path": str(resolved),
                "bytes_written": len(content.encode("utf-8")),
            },
        )

    def _list(self, path: str | None) -> ToolResult:
        try:
            resolved = resolve_in_workspace(
                self._workspace, path if path else ".", allow_root=True
            )
        except PathPolicyError as exc:
            return ToolResult(ok=False, error=f"list rejected: {exc}")
        if not resolved.exists():
            return ToolResult(ok=False, error=f"directory not found: {path}")
        if not resolved.is_dir():
            return ToolResult(ok=False, error=f"not a directory: {path}")

        entries: list[dict] = []
        truncated = False
        try:
            for current, dirnames, filenames in os.walk(resolved):
                dirnames.sort()
                for dirname in dirnames:
                    full = Path(current) / dirname
                    entries.append(
                        {
                            "path": full.relative_to(self._workspace).as_posix(),
                            "type": "dir",
                            "size": None,
                        }
                    )
                for filename in sorted(filenames):
                    full = Path(current) / filename
                    try:
                        size = full.stat().st_size
                    except OSError:
                        size = None
                    entries.append(
                        {
                            "path": full.relative_to(self._workspace).as_posix(),
                            "type": "file",
                            "size": size,
                        }
                    )
                if len(entries) >= self._max_list:
                    truncated = True
                    break
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not list {path}: {exc}")

        entries = entries[: self._max_list]
        return ToolResult(
            ok=True,
            data={
                "path": path or ".",
                "count": len(entries),
                "truncated": truncated,
                "entries": entries,
            },
        )

    # -- tool entrypoint -------------------------------------------------------

    def run(self, inputs: dict) -> ToolResult:
        """Dispatch on ``operation``. Inputs: {operation, path?, content?}."""
        operation = inputs.get("operation")
        if operation not in ("read", "write", "list"):
            return ToolResult(
                ok=False,
                error=(
                    f"operation must be one of 'read'|'write'|'list', got {operation!r}"
                ),
            )
        path = inputs.get("path")

        if operation == "list":
            return self._list(path if isinstance(path, str) else None)

        if not isinstance(path, str) or not path.strip():
            return ToolResult(
                ok=False, error=f"operation {operation!r} requires a non-empty 'path'"
            )
        if operation == "read":
            return self._read(path)
        return self._write(path, inputs.get("content"))
