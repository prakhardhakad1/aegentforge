"""Test bootstrap for backend/integrations/tests.

The export module is imported by the backend as the top-level package
``integrations`` (backend runs with cwd=backend/). When pytest is invoked from
the repo root (``python -m pytest backend/integrations/tests -q``), the
backend/ directory is NOT on sys.path — add it here before anything imports
``integrations``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
