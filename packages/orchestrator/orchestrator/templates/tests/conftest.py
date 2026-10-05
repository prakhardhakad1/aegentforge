"""conftest for orchestrator.templates tests — path bootstrap only.

The shared venv normally has ``orchestrator`` pip-installed (editable); this
fallback makes the tests runnable even from a bare checkout where the package
is not installed, by putting ``packages/orchestrator`` on ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]  # .../packages/orchestrator

try:  # pragma: no cover - depends on install state
    import orchestrator  # noqa: F401
except ImportError:  # pragma: no cover - bare-checkout fallback
    if str(_PACKAGE_ROOT) not in sys.path:
        sys.path.insert(0, str(_PACKAGE_ROOT))
