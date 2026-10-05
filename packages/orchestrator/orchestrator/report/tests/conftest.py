"""Test bootstrap for orchestrator.report tests (Agent 6).

The orchestrator package may not be pip-installed yet (Agent 3 owns its
pyproject), so we put ``packages/orchestrator`` on sys.path ourselves. This
file lives inside the report subpackage and touches nothing outside it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
# tests -> report -> orchestrator/pkg -> packages/orchestrator
_ORCH_PKG_ROOT = _TESTS_DIR.parents[2]
_REPO_ROOT = _TESTS_DIR.parents[4]

for _entry in (str(_ORCH_PKG_ROOT), str(_REPO_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
