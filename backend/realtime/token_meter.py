"""Token / cost accounting for AgentForge runs (Agent 7).

The pinned token_update payload (docs/INTERFACES.md) is::

    {"agent": "analyst", "input_tokens": 1200, "output_tokens": 340,
     "cost_usd": 0.000169, "run_total_usd": 0.000927}

:class:`TokenMeter` is the shared accountant used by both the orchestrator
engine (live mode) and :mod:`realtime.simulate` (demo mode):

* per-agent input/output token counters,
* cost math from env ``COST_PER_1M_INPUT_TOKENS`` / ``COST_PER_1M_OUTPUT_TOKENS``
  (USD per 1M tokens, defaults 0.11 / 0.11),
* run totals and a :meth:`TokenMeter.snapshot` matching the pinned
  ``token_usage`` shape (``RunResult.token_usage`` / RunSnapshot),
* :meth:`TokenMeter.merge` for combining meters (e.g. engine + critic passes),
* a post-run breakdown table (:meth:`TokenMeter.breakdown_table` /
  :meth:`TokenMeter.format_breakdown`).

Standalone by design: stdlib only, no app imports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Union

#: Env var names (canonical, from docs/INTERFACES.md § "Env vars").
ENV_COST_PER_1M_INPUT = "COST_PER_1M_INPUT_TOKENS"
ENV_COST_PER_1M_OUTPUT = "COST_PER_1M_OUTPUT_TOKENS"

#: Default USD per 1M tokens when env vars are unset/invalid.
DEFAULT_COST_PER_1M_INPUT: float = 0.11
DEFAULT_COST_PER_1M_OUTPUT: float = 0.11


def _rate_from_env(name: str, default: float) -> float:
    """Read a USD-per-1M-token rate from the environment; fall back safely."""
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return default
    if rate < 0:  # negative prices are a config error, not a discount
        return default
    return rate


def cost_of_tokens(
    input_tokens: float,
    output_tokens: float,
    cost_per_1m_input: Optional[float] = None,
    cost_per_1m_output: Optional[float] = None,
) -> float:
    """USD cost for the given token counts at the given per-1M rates."""
    in_rate = (
        DEFAULT_COST_PER_1M_INPUT if cost_per_1m_input is None else cost_per_1m_input
    )
    out_rate = (
        DEFAULT_COST_PER_1M_OUTPUT if cost_per_1m_output is None else cost_per_1m_output
    )
    return round(
        (float(input_tokens) / 1_000_000.0) * in_rate
        + (float(output_tokens) / 1_000_000.0) * out_rate,
        6,
    )


@dataclass
class _AgentTally:
    """Internal per-agent accumulator."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass
class TokenMeter:
    """Per-agent token/cost counter for one run.

    >>> meter = TokenMeter(cost_per_1m_input_tokens=0.11, cost_per_1m_output_tokens=0.11)
    >>> meter.record("analyst", input_tokens=1_000_000, output_tokens=1_000_000)
    {'input_tokens': 1000000, 'output_tokens': 1000000, 'cost_usd': 0.22}
    >>> meter.snapshot()["totals"]["cost_usd"]
    0.22
    """

    cost_per_1m_input_tokens: float = field(
        default_factory=lambda: _rate_from_env(
            ENV_COST_PER_1M_INPUT, DEFAULT_COST_PER_1M_INPUT
        )
    )
    cost_per_1m_output_tokens: float = field(
        default_factory=lambda: _rate_from_env(
            ENV_COST_PER_1M_OUTPUT, DEFAULT_COST_PER_1M_OUTPUT
        )
    )
    per_agent: dict[str, _AgentTally] = field(default_factory=dict)

    # ── recording ────────────────────────────────────────────────────────

    def record(
        self,
        agent: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> dict[str, Any]:
        """Add one usage batch for ``agent``; returns that agent's new tally.

        Cost is computed at this meter's rates. Negative/non-numeric counts
        are clamped to 0 rather than corrupting the totals.
        """
        name = str(agent) if agent else "unknown"
        tally = self.per_agent.setdefault(name, _AgentTally())
        tally.input_tokens += self._clamp(input_tokens)
        tally.output_tokens += self._clamp(output_tokens)
        tally.cost_usd = cost_of_tokens(
            tally.input_tokens,
            tally.output_tokens,
            self.cost_per_1m_input_tokens,
            self.cost_per_1m_output_tokens,
        )
        return tally.as_dict()

    def ingest_token_update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Fold a pinned ``token_update`` payload into the meter.

        Deltas (``input_tokens``/``output_tokens``) are accumulated; the
        payload's own ``cost_usd`` is honoured when present (producers may
        use different rates) and recomputed from the running counts otherwise.
        Returns the agent's updated tally dict.
        """
        name = str(payload.get("agent") or "unknown")
        raw_in = self._clamp(payload.get("input_tokens", 0))
        raw_out = self._clamp(payload.get("output_tokens", 0))
        tally = self.per_agent.setdefault(name, _AgentTally())
        tally.input_tokens += raw_in
        tally.output_tokens += raw_out
        declared_cost = payload.get("cost_usd")
        if isinstance(declared_cost, (int, float)) and not isinstance(
            declared_cost, bool
        ) and declared_cost >= 0:
            tally.cost_usd += float(declared_cost)
        else:
            tally.cost_usd = cost_of_tokens(
                tally.input_tokens,
                tally.output_tokens,
                self.cost_per_1m_input_tokens,
                self.cost_per_1m_output_tokens,
            )
        return tally.as_dict()

    # ── reporting ────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Pinned ``token_usage`` shape: ``{"per_agent": {...}, "totals": {...}}``."""
        per_agent = {
            name: tally.as_dict() for name, tally in sorted(self.per_agent.items())
        }
        totals = {
            "input_tokens": sum(t["input_tokens"] for t in per_agent.values()),
            "output_tokens": sum(t["output_tokens"] for t in per_agent.values()),
            "cost_usd": round(
                sum(t["cost_usd"] for t in per_agent.values()), 6
            ),
        }
        return {"per_agent": per_agent, "totals": totals}

    def run_total_usd(self) -> float:
        """Current total cost across all agents (for token_update payloads)."""
        return round(
            sum(tally.cost_usd for tally in self.per_agent.values()), 6
        )

    def merge(
        self,
        other: Union["TokenMeter", Mapping[str, Any], None],
    ) -> "TokenMeter":
        """Merge another meter or a ``token_usage`` snapshot dict into self.

        Token counts add up; per-agent cost is recomputed at *this* meter's
        rates for the summed counts so a merged meter stays internally
        consistent. Returns ``self`` for chaining.
        """
        if other is None:
            return self
        if isinstance(other, TokenMeter):
            for name, tally in other.per_agent.items():
                mine = self.per_agent.setdefault(name, _AgentTally())
                mine.input_tokens += tally.input_tokens
                mine.output_tokens += tally.output_tokens
                mine.cost_usd = cost_of_tokens(
                    mine.input_tokens,
                    mine.output_tokens,
                    self.cost_per_1m_input_tokens,
                    self.cost_per_1m_output_tokens,
                )
            return self
        if isinstance(other, Mapping):
            per_agent = other.get("per_agent")
            if isinstance(per_agent, Mapping):
                for name, usage in per_agent.items():
                    if isinstance(usage, Mapping):
                        self.record(
                            str(name),
                            self._clamp(usage.get("input_tokens", 0)),
                            self._clamp(usage.get("output_tokens", 0)),
                        )
            return self
        raise TypeError(
            f"merge() expects a TokenMeter or a snapshot dict, got {type(other).__name__}"
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Mapping[str, Any],
        *,
        cost_per_1m_input_tokens: Optional[float] = None,
        cost_per_1m_output_tokens: Optional[float] = None,
    ) -> "TokenMeter":
        """Build a meter from a ``token_usage`` snapshot dict (totals kept)."""
        meter = cls(
            cost_per_1m_input_tokens=(
                DEFAULT_COST_PER_1M_INPUT
                if cost_per_1m_input_tokens is None
                else cost_per_1m_input_tokens
            ),
            cost_per_1m_output_tokens=(
                DEFAULT_COST_PER_1M_OUTPUT
                if cost_per_1m_output_tokens is None
                else cost_per_1m_output_tokens
            ),
        )
        meter.merge(snapshot)
        return meter

    @classmethod
    def from_events(
        cls,
        events: Iterable[Mapping[str, Any]],
        *,
        cost_per_1m_input_tokens: Optional[float] = None,
        cost_per_1m_output_tokens: Optional[float] = None,
    ) -> "TokenMeter":
        """Build a meter by replaying ``token_update`` events (envelopes ok)."""
        meter = cls(
            cost_per_1m_input_tokens=(
                DEFAULT_COST_PER_1M_INPUT
                if cost_per_1m_input_tokens is None
                else cost_per_1m_input_tokens
            ),
            cost_per_1m_output_tokens=(
                DEFAULT_COST_PER_1M_OUTPUT
                if cost_per_1m_output_tokens is None
                else cost_per_1m_output_tokens
            ),
        )
        for event in events:
            if not isinstance(event, Mapping):
                continue
            if event.get("type") not in (None, "token_update"):
                continue
            payload = event.get("payload") if "payload" in event else event
            if isinstance(payload, Mapping):
                meter.ingest_token_update(payload)
        return meter

    # ── post-run breakdown ───────────────────────────────────────────────

    def breakdown_table(self) -> list[dict[str, Any]]:
        """Per-agent breakdown rows (sorted by cost desc) for reports/UI.

        Row shape: ``{"agent","input_tokens","output_tokens","total_tokens",
        "cost_usd","cost_share"}`` where ``cost_share`` is the agent's share
        of run cost in ``[0, 1]`` (0.0 when the run cost is 0).
        """
        snap = self.snapshot()
        total_cost = snap["totals"]["cost_usd"]
        rows: list[dict[str, Any]] = []
        for name, usage in snap["per_agent"].items():
            total_tokens = usage["input_tokens"] + usage["output_tokens"]
            rows.append(
                {
                    "agent": name,
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "total_tokens": total_tokens,
                    "cost_usd": usage["cost_usd"],
                    "cost_share": (
                        round(usage["cost_usd"] / total_cost, 4)
                        if total_cost > 0
                        else 0.0
                    ),
                }
            )
        rows.sort(key=lambda row: (-row["cost_usd"], row["agent"]))
        return rows

    def format_breakdown(self) -> str:
        """Human-readable ASCII breakdown table (for logs / report appendix)."""
        rows = self.breakdown_table()
        if not rows:
            return "No token usage recorded."
        headers = ("agent", "input", "output", "total", "cost_usd", "share")
        widths = [len(h) for h in headers]
        table: list[list[str]] = []
        for row in rows:
            cells = [
                row["agent"],
                f"{row['input_tokens']:,}",
                f"{row['output_tokens']:,}",
                f"{row['total_tokens']:,}",
                f"${row['cost_usd']:.6f}",
                f"{row['cost_share'] * 100:.1f}%",
            ]
            for i, cell in enumerate(cells):
                widths[i] = max(widths[i], len(cell))
            table.append(cells)
        totals = self.snapshot()["totals"]
        footer = [
            "TOTAL",
            f"{totals['input_tokens']:,}",
            f"{totals['output_tokens']:,}",
            f"{totals['input_tokens'] + totals['output_tokens']:,}",
            f"${totals['cost_usd']:.6f}",
            "100.0%",
        ]

        def fmt(cells: list[str]) -> str:
            padded = [c.ljust(widths[i]) for i, c in enumerate(cells)]
            return "  ".join(padded).rstrip()

        lines = [fmt(list(headers)), fmt(["-" * w for w in widths])]
        lines.extend(fmt(cells) for cells in table)
        lines.append(fmt(["-" * w for w in widths]))
        lines.append(fmt(footer))
        return "\n".join(lines)

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _clamp(value: Any) -> int:
        """Coerce a token count to a non-negative int (bad input → 0)."""
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return max(0, value)
        if isinstance(value, float):
            return max(0, int(value))
        try:
            return max(0, int(str(value).strip()))
        except (TypeError, ValueError):
            return 0


__all__ = [
    "DEFAULT_COST_PER_1M_INPUT",
    "DEFAULT_COST_PER_1M_OUTPUT",
    "ENV_COST_PER_1M_INPUT",
    "ENV_COST_PER_1M_OUTPUT",
    "TokenMeter",
    "cost_of_tokens",
]
