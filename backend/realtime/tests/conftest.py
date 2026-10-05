"""Test fixtures for backend/realtime/tests.

Puts ``backend/`` on sys.path so the pinned import root ``realtime`` resolves
no matter where pytest is invoked from (repo root per the brief, or backend/).
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
