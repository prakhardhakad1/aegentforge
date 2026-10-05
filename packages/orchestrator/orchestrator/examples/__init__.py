"""orchestrator.examples — three worked missions with expected plan JSON.

Each example pairs a realistic business mission with the plan the heuristic
planner produces offline (LLM_MODE=mock) and, where relevant, a small bundled
sample CSV. ``python -m orchestrator.examples.run_demo`` executes one
end-to-end and prints every pinned event as it fires.
"""

from __future__ import annotations

from .missions import EXAMPLES, ExampleMission, get_example, list_examples

__all__ = ["EXAMPLES", "ExampleMission", "get_example", "list_examples"]
