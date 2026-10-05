"""AgentForge realtime package (Agent 7).

Canonical, dependency-light realtime layer for the live run experience:

* :mod:`realtime.events`     — pinned event envelope models + constructors.
* :mod:`realtime.broadcaster`— per-run pub/sub with history + replay.
* :mod:`realtime.token_meter`— per-agent token/cost accounting.
* :mod:`realtime.simulate`   — offline demo simulator (SimulatedRunPlayer).

Everything here is stdlib + pydantic only: no FastAPI, no DB, no LLM, no
network. The backend imports it with ``cwd=backend`` (import root ``realtime``).
"""

from __future__ import annotations

__all__ = ["broadcaster", "events", "simulate", "token_meter"]
