"""Shared pytest setup for agentforge_tools tests.

* Forces ``MPLBACKEND=Agg`` before any matplotlib import (headless).
* Removes ``BRAVE_API_KEY`` so provider selection is deterministic offline.
* Ensures ``packages/tools`` is importable even when the package is not
  pip-installed (tests are run from the repo root).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.pop("BRAVE_API_KEY", None)

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import pytest  # noqa: E402


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A fresh per-test workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def fixtures_dir() -> Path:
    """Directory of committed CSV fixtures."""
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_tool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tools from ambient env vars that would change behavior."""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("SANDBOX_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SANDBOX_MEMORY_MB", raising=False)
    monkeypatch.delenv("SANDBOX_MAX_OUTPUT_CHARS", raising=False)
    monkeypatch.delenv("FILE_MAX_READ_BYTES", raising=False)
    monkeypatch.delenv("FILE_MAX_WRITE_BYTES", raising=False)
    monkeypatch.delenv("CSV_MAX_FILE_MB", raising=False)
    monkeypatch.delenv("CSV_ROW_CAP", raising=False)
