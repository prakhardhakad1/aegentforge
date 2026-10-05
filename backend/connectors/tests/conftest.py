"""Pytest bootstrap for the connectors test suite.

Adds ``backend/`` to ``sys.path`` so ``import connectors`` works regardless of
the invocation directory (the brief runs pytest from the repo root; the live
backend runs with cwd=backend).
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
