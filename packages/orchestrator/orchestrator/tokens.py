"""orchestrator.tokens — per-agent token and cost accounting (Agent 3).

Feeds the pinned ``token_update`` events and the RunResult ``token_usage``
block:

    {"per_agent": {"analyst": {"input_tokens": 1200, "output_tokens": 340,
                               "cost_usd": 0.00017}, ...},
     "totals": {"input_tokens": ..., "output_tokens": ..., "cost_usd": ...}}

Costs come from env (Agent 7's contract, docs/INTERFACES.md):
    COST_PER_1M_INPUT_TOKENS  — USD per 1M input tokens
    COST_PER_1M_OUTPUT_TOKENS — USD per 1M output tokens
Missing/garbage values fall back to the .env.example defaults (0.11) so the
meter always shows a sane estimate; the estimate is labeled as such in NOTES.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = ["TokenAccountant", "AgentUsage"]

_DEFAULT_COST_PER_1M = 0.11


@dataclass
class AgentUsage:
    """Running counters for one agent role."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def as_dict(self) -> dict[str, int]:
        """JSON-safe dict (without cost; see TokenAccountant)."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "calls": self.calls,
        }


@dataclass
class TokenAccountant:
    """Per-agent token counters plus USD cost estimation.

    ``add`` is the only mutation entry point; it returns the snapshot dict
    for the pinned ``token_update`` payload so the engine can emit it
    immediately after each LLM call.
    """

    cost_per_1m_input: float = _DEFAULT_COST_PER_1M
    cost_per_1m_output: float = _DEFAULT_COST_PER_1M
    per_agent: dict[str, AgentUsage] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "TokenAccountant":
        """Build with the canonical COST_PER_1M_* env vars."""
        return cls(
            cost_per_1m_input=_env_cost("COST_PER_1M_INPUT_TOKENS"),
            cost_per_1m_output=_env_cost("COST_PER_1M_OUTPUT_TOKENS"),
        )

    # -- mutation -----------------------------------------------------------

    def add(self, agent: str, input_tokens: int, output_tokens: int) -> dict[str, object]:
        """Record one LLM call; returns the ``token_update`` payload snapshot."""
        usage = self.per_agent.setdefault(agent, AgentUsage())
        usage.input_tokens += max(0, int(input_tokens))
        usage.output_tokens += max(0, int(output_tokens))
        usage.calls += 1
        return self.snapshot(agent)

    # -- reporting ----------------------------------------------------------

    def agent_cost(self, agent: str) -> float:
        """Estimated USD cost for one agent role so far."""
        usage = self.per_agent.get(agent)
        if usage is None:
            return 0.0
        return self._cost(usage.input_tokens, usage.output_tokens)

    def snapshot(self, agent: str) -> dict[str, object]:
        """``token_update`` payload for *agent* with run-wide totals."""
        usage = self.per_agent.get(agent, AgentUsage())
        return {
            "agent": agent,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": round(self.agent_cost(agent), 6),
            "run_total_usd": round(self.total_cost(), 6),
        }

    def total_cost(self) -> float:
        """Estimated USD cost across all agents."""
        return sum(
            self._cost(u.input_tokens, u.output_tokens) for u in self.per_agent.values()
        )

    def to_dict(self) -> dict[str, object]:
        """Pinned RunResult ``token_usage`` shape."""
        per_agent: dict[str, dict[str, object]] = {}
        for agent, usage in self.per_agent.items():
            per_agent[agent] = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": round(self.agent_cost(agent), 6),
            }
        totals = {
            "input_tokens": sum(u.input_tokens for u in self.per_agent.values()),
            "output_tokens": sum(u.output_tokens for u in self.per_agent.values()),
            "cost_usd": round(self.total_cost(), 6),
        }
        return {"per_agent": per_agent, "totals": totals}

    # -- helpers ------------------------------------------------------------

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        """USD for the given token counts at the configured per-1M rates."""
        return (
            input_tokens / 1_000_000 * self.cost_per_1m_input
            + output_tokens / 1_000_000 * self.cost_per_1m_output
        )


def _env_cost(name: str) -> float:
    """Parse a cost env var; log and fall back to the default on garbage."""
    raw = os.environ.get(name, "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        if raw:
            logger.warning("Env %s=%r is not a number; using default %s", name, raw, _DEFAULT_COST_PER_1M)
        return _DEFAULT_COST_PER_1M
