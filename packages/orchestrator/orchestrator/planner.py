"""orchestrator.planner — mission to validated subtask DAG (Agent 3).

The Planner turns a one-sentence mission (+ optional template id and dataset
columns) into a validated DAG of subtasks assigned to the specialist roles
(researcher / analyst / forecaster / critic).

Two strategies, chosen per run:

* **LLM-driven** (live mode): one strict ``complete_json`` call with a pinned
  shape ``{"subtasks": [{id, title, agent, depends_on, guidance}]}``. The
  output is normalized (deduped ids, deps filtered to known ids, critic wired
  to see every worker) and validated before it is trusted.
* **Heuristic fallback** (mock/offline, or whenever the LLM plan fails
  validation): a transparent rule-based planner — keyword detection picks the
  role set (research / data / predict signals, dataset presence forces the
  analyst) and a sensible default chain per role set is emitted, always
  ending with the critic plus a conditional revision-pass slot.

Validation guarantees (any violation aborts the LLM plan in favor of the
heuristic one):

* unique, URL-safe subtask ids; 1..MAX_SUBTASKS subtasks
* agent roles are worker roles (the planner itself is not scheduled)
* depends_on references exist; no self-dependencies; graph is acyclic (Kahn)
* exactly one critic subtask, placed near the end (nothing may run after it
  except revision slots)
* revision slots (optional) depend on the critic and are executed
  conditionally by the engine only when the critic flags outputs
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from orchestrator.llm import LLMClient
from orchestrator.messages import PENDING

logger = logging.getLogger(__name__)

__all__ = ["Subtask", "Plan", "PlanValidationError", "Planner", "WORKER_ROLES"]

# Pinned worker roles (docs/INTERFACES.md) — the planner never schedules
# itself; "planner" appears only as the event agent for plan_created.
WORKER_ROLES: tuple[str, ...] = ("researcher", "analyst", "forecaster", "critic")

MAX_SUBTASKS = 10
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")


class PlanValidationError(ValueError):
    """Raised when a plan (LLM or heuristic) violates the DAG contract."""


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Subtask:
    """One planned unit of work for a specialist agent."""

    id: str
    title: str
    agent: str
    depends_on: list[str] = field(default_factory=list)
    guidance: str = ""
    status: str = PENDING
    # Internal flag: revision slots are conditional engine-managed stages.
    is_revision_slot: bool = False

    def to_dict(self, include_guidance: bool = True) -> dict[str, object]:
        """JSON-safe dict. Event payloads omit guidance (pinned schema keeps
        id/title/agent/depends_on/status); RunResult.plan keeps it."""
        payload: dict[str, object] = {
            "id": self.id,
            "title": self.title,
            "agent": self.agent,
            "depends_on": list(self.depends_on),
            "status": self.status,
        }
        if include_guidance:
            payload["guidance"] = self.guidance
        return payload


@dataclass
class Plan:
    """An ordered set of subtasks forming a validated DAG."""

    subtasks: list[Subtask] = field(default_factory=list)
    strategy: str = "heuristic"  # "llm" | "heuristic" | "template"
    notes: list[str] = field(default_factory=list)

    # -- lookup -------------------------------------------------------------

    def subtask(self, subtask_id: str) -> Subtask | None:
        """Find a subtask by id (None if absent)."""
        return next((s for s in self.subtasks if s.id == subtask_id), None)

    @property
    def critic(self) -> Subtask | None:
        """The single critic subtask, if present."""
        return next((s for s in self.subtasks if s.agent == "critic"), None)

    @property
    def revision_slots(self) -> list[Subtask]:
        """Conditional revision-pass slots."""
        return [s for s in self.subtasks if s.is_revision_slot]

    @property
    def worker_subtasks(self) -> list[Subtask]:
        """Action subtasks (everything except revision slots)."""
        return [s for s in self.subtasks if not s.is_revision_slot]

    # -- serialization -------------------------------------------------------

    def to_dicts(self, include_guidance: bool = True) -> list[dict[str, object]]:
        """All subtasks as JSON-safe dicts (plan order)."""
        return [s.to_dict(include_guidance=include_guidance) for s in self.subtasks]

    # -- graph ---------------------------------------------------------------

    def topological_order(self) -> list[Subtask]:
        """Kahn's algorithm; deterministic (id-sorted among ready nodes).

        Raises:
            PlanValidationError: if the graph contains a cycle.
        """
        in_degree = {s.id: 0 for s in self.subtasks}
        dependents: dict[str, list[str]] = {s.id: [] for s in self.subtasks}
        for sub in self.subtasks:
            for dep in sub.depends_on:
                in_degree[sub.id] += 1
                dependents[dep].append(sub.id)
        ready = sorted([sid for sid, deg in in_degree.items() if deg == 0])
        ordered: list[str] = []
        while ready:
            sid = ready.pop(0)
            ordered.append(sid)
            for child in dependents[sid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    ready.append(child)
            ready.sort()
        if len(ordered) != len(self.subtasks):
            stuck = sorted(set(in_degree) - set(ordered))
            raise PlanValidationError(f"plan graph contains a cycle involving: {stuck}")
        return [self.subtask(sid) for sid in ordered]  # type: ignore[misc]

    # -- validation ------------------------------------------------------------

    def validate(self) -> None:
        """Enforce the full DAG contract; raises PlanValidationError."""
        if not self.subtasks:
            raise PlanValidationError("plan has no subtasks")
        if len(self.subtasks) > MAX_SUBTASKS:
            raise PlanValidationError(
                f"plan has {len(self.subtasks)} subtasks (max {MAX_SUBTASKS})"
            )

        seen: set[str] = set()
        for sub in self.subtasks:
            if not _ID_RE.match(sub.id):
                raise PlanValidationError(f"invalid subtask id {sub.id!r}")
            if sub.id in seen:
                raise PlanValidationError(f"duplicate subtask id {sub.id!r}")
            seen.add(sub.id)
            if sub.agent not in WORKER_ROLES:
                raise PlanValidationError(
                    f"subtask {sub.id!r} has non-worker agent {sub.agent!r}"
                )
            if not sub.title or not sub.title.strip():
                raise PlanValidationError(f"subtask {sub.id!r} has an empty title")

        for sub in self.subtasks:
            for dep in sub.depends_on:
                if dep == sub.id:
                    raise PlanValidationError(f"subtask {sub.id!r} depends on itself")
                if dep not in seen:
                    raise PlanValidationError(
                        f"subtask {sub.id!r} depends on unknown subtask {dep!r}"
                    )

        critics = [s for s in self.subtasks if s.agent == "critic"]
        if len(critics) != 1:
            raise PlanValidationError(
                f"plan must contain exactly one critic subtask, found {len(critics)}"
            )
        critic_id = critics[0].id

        self.topological_order()  # raises on cycles

        # Nothing may run after the critic except revision slots.
        for sub in self.subtasks:
            if sub.id == critic_id or sub.is_revision_slot:
                continue
            if _is_dependent_of_critic(self, sub.id, critic_id):
                raise PlanValidationError(
                    f"subtask {sub.id!r} runs after the critic; only revision "
                    "slots may depend on it"
                )

        # Revision slots must hang off the critic and be worker assignments.
        for slot in self.revision_slots:
            if critic_id not in slot.depends_on:
                raise PlanValidationError(
                    f"revision slot {slot.id!r} must depend on the critic {critic_id!r}"
                )

    def normalize(self) -> None:
        """Repair common LLM-plan sloppiness before validation.

        * strips whitespace from ids/titles
        * dedupes depends_on, drops unknown/self dependencies
        * renames duplicate ids deterministically (t2 -> t2_dup1)
        * ensures the single critic transitively sees every worker subtask
          by appending missing dependencies (re-wired conservatively: the
          critic gains deps only on subtasks that are not the critic itself
          and not revision slots)
        """
        used: set[str] = set()
        for index, sub in enumerate(self.subtasks):
            sub.id = sub.id.strip() or f"t{index + 1}"
            sub.title = sub.title.strip()
            sub.agent = sub.agent.strip().lower()
            base = sub.id
            bump = 1
            while sub.id in used:
                bump += 1
                sub.id = f"{base}_dup{bump}"
            used.add(sub.id)

        known = {s.id for s in self.subtasks}
        for sub in self.subtasks:
            sub.depends_on = [
                dep for dep in dict.fromkeys(dep.strip() for dep in sub.depends_on)
                if dep in known and dep != sub.id
            ]

        critics = [s for s in self.subtasks if s.agent == "critic"]
        if len(critics) == 1:
            critic = critics[0]
            for sub in self.subtasks:
                if sub.agent != "critic" and not sub.is_revision_slot:
                    if sub.id not in critic.depends_on:
                        critic.depends_on.append(sub.id)


def _reaches(plan: Plan, start: str, target: str) -> bool:
    """True when a directed path start -> target exists."""
    stack, visited = [start], set()
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        sub = plan.subtask(current)
        if sub:
            stack.extend(sub.depends_on)
    return False


def _is_dependent_of_critic(plan: Plan, subtask_id: str, critic_id: str) -> bool:
    """True when *subtask_id* transitively depends on the critic (runs after)."""
    return _reaches(plan, subtask_id, critic_id) and subtask_id != critic_id


# ---------------------------------------------------------------------------
# Heuristic (offline) planner
# ---------------------------------------------------------------------------

_RESEARCH_KEYWORDS = (
    "market", "research", "competitor", "competitive", "landscape", "benchmark",
    "industry", "feedback", "best practice", "what are", "why do",
    "trend", "ev ", "charging", "review site",
)
_DATA_KEYWORDS = (
    "data", "csv", "dataset", "metric", "churn", "revenue", "sales", "ticket",
    "conversion", "retention", "kpi", "stats", "spike", "decline", "dropped",
    "analyze", "analysis", "usage", "numbers", "q3", "quarter",
)
_PREDICT_KEYWORDS = (
    "predict", "forecast", "projection", "outlook", "next quarter", "next month",
    "trajectory", "anticipate", "expect", "will grow", "adoption",
)


def _signals(mission: str, dataset_columns: list[str] | None) -> dict[str, bool]:
    """Keyword + dataset signals driving the heuristic plan."""
    text = mission.lower()
    return {
        "research": any(k in text for k in _RESEARCH_KEYWORDS),
        "data": bool(dataset_columns) or any(k in text for k in _DATA_KEYWORDS),
        "predict": any(k in text for k in _PREDICT_KEYWORDS),
    }


_GUIDANCE = {
    "researcher": (
        "Search public sources for context, benchmarks and comparable cases "
        "relevant to this mission. Cite every finding with a source URL."
    ),
    "analyst": (
        "Analyze the dataset: profile columns, quantify the key movement, "
        "break it down by segment, and produce charts that support each insight."
    ),
    "forecaster": (
        "Using the analyst/researcher outputs, project the headline metric "
        "forward with explicit confidence and basis for every prediction."
    ),
    "critic": (
        "Review every artifact and step output. Flag unsupported or vague "
        "claims and request revisions; finish with a clear verdict."
    ),
}


def heuristic_plan(mission: str, dataset_columns: list[str] | None = None) -> Plan:
    """Rule-based plan: keyword detection -> default DAG for the role set.

    Chain: researcher (if research signal) -> analyst (if data signal or a
    dataset is attached) -> forecaster (if predict signal) -> critic, with
    one conditional revision slot after the critic. A plan always contains at
    least one worker plus the critic.
    """
    signals = _signals(mission, dataset_columns)
    notes: list[str] = [f"heuristic signals: {signals}"]
    chain: list[str] = []
    if signals["research"]:
        chain.append("researcher")
    if signals["data"]:
        chain.append("analyst")
    if not chain:  # sensible default: light research + critic
        chain.append("researcher")
        notes.append("no strong signal detected; defaulting to researcher + critic")
    if signals["predict"]:
        chain.append("forecaster")

    subtasks: list[Subtask] = []
    previous: str | None = None
    for index, role in enumerate(chain, start=1):
        subtasks.append(
            Subtask(
                id=f"t{index}",
                title=_title_for(role, mission),
                agent=role,
                depends_on=[previous] if previous else [],
                guidance=_GUIDANCE[role],
            )
        )
        previous = f"t{index}"

    critic_id = f"t{len(chain) + 1}"
    subtasks.append(
        Subtask(
            id=critic_id,
            title=f"Critical review of outputs for: {mission_split(mission)}",
            agent="critic",
            depends_on=[s.id for s in subtasks],
            guidance=_GUIDANCE["critic"],
        )
    )
    subtasks.append(
        Subtask(
            id=f"{critic_id}_rev",
            title="Revision pass for flagged subtasks (runs only if the critic flags issues)",
            agent=chain[-1],
            depends_on=[critic_id],
            guidance=(
                "CONDITIONAL REVISION SLOT. The engine runs this pass only when "
                "the critic requests revisions; each flagged subtask is re-run "
                "by its own specialist with the critic's instruction attached."
            ),
            is_revision_slot=True,
        )
    )

    plan = Plan(subtasks=subtasks, strategy="heuristic", notes=notes)
    plan.validate()
    return plan


def mission_split(mission: str) -> str:
    """First few words of the mission for compact titles."""
    words = mission.strip().split()
    return " ".join(words[:4]) if words else "mission"


def _title_for(role: str, mission: str) -> str:
    """Human-readable subtask title per role."""
    short = mission_split(mission)
    titles = {
        "researcher": f"Research context for: {short}",
        "analyst": f"Analyze the data behind: {short}",
        "forecaster": f"Forecast the trajectory for: {short}",
    }
    return titles.get(role, f"{role} subtask for: {short}")


# ---------------------------------------------------------------------------
# Template adapter (Agent 8's orchestrator.templates, imported defensively)
# ---------------------------------------------------------------------------


def template_plan(template_id: str, mission: str) -> Plan | None:
    """Build a Plan from a marketplace template, if the package is available.

    Looks for (in order): ``get_template(template_id)`` and a module-level
    ``TEMPLATES`` mapping. Every access is guarded — a missing/changed
    Agent 8 API simply yields ``None`` and the planner falls back.
    """
    try:
        import orchestrator.templates as templates_mod  # noqa: PLC0415
    except Exception:  # pragma: no cover - Agent 8 lands separately
        return None

    template: dict[str, Any] | object | None = None
    try:
        getter = getattr(templates_mod, "get_template", None)
        if callable(getter):
            template = getter(template_id)
        if template is None:
            mapping = getattr(templates_mod, "TEMPLATES", None)
            if isinstance(mapping, dict):
                template = mapping.get(template_id)
    except Exception as exc:  # pragma: no cover - never let a template crash planning
        logger.warning("template lookup failed for %r: %s", template_id, exc)
        return None

    if template is None:
        return None

    expected_dag = _extract_field_from_template(template, "expected_dag")
    if not isinstance(expected_dag, list) or not expected_dag:
        return None

    subtasks: list[Subtask] = []
    for index, node in enumerate(expected_dag, start=1):
        if not isinstance(node, dict):
            continue
        subtasks.append(
            Subtask(
                id=str(node.get("id") or f"t{index}"),
                title=str(node.get("title") or f"Template step {index}"),
                agent=str(node.get("agent") or "researcher"),
                depends_on=[str(d) for d in node.get("depends_on", []) if isinstance(d, str)],
                guidance=str(
                    node.get("guidance")
                    or _extract_field_from_template(template, "planner_prompt")
                    or _GUIDANCE.get(str(node.get("agent")), "")
                ),
            )
        )
    if not subtasks:
        return None

    # Guarantee the review stage + revision slot even if the template omits them.
    if not any(s.agent == "critic" for s in subtasks):
        subtasks.append(
            Subtask(
                id=f"t{len(subtasks) + 1}",
                title="Critical review",
                agent="critic",
                depends_on=[s.id for s in subtasks],
                guidance=_GUIDANCE["critic"],
            )
        )
    critic = next(s for s in subtasks if s.agent == "critic")
    subtasks.append(
        Subtask(
            id=f"{critic.id}_rev",
            title="Revision pass for flagged subtasks (runs only if the critic flags issues)",
            agent="researcher",
            depends_on=[critic.id],
            guidance=_GUIDANCE["critic"],
            is_revision_slot=True,
        )
    )

    plan = Plan(subtasks=subtasks, strategy="template", notes=[f"template {template_id}"])
    plan.normalize()
    try:
        plan.validate()
    except PlanValidationError as exc:
        logger.warning("template %r produced an invalid plan (%s); ignoring", template_id, exc)
        return None
    return plan


def _extract_field_from_template(template: object, name: str) -> object:
    """Read a field from either a dataclass-ish template or a dict."""
    if isinstance(template, dict):
        return template.get(name)
    return getattr(template, name, None)


# ---------------------------------------------------------------------------
# Planner facade
# ---------------------------------------------------------------------------

_LLM_PLAN_SCHEMA_HINT = (
    '{"subtasks": [{"id": "t1", "title": "...", "agent": "researcher|analyst|'
    'forecaster|critic", "depends_on": ["<id>"], "guidance": "specific '
    'instructions for that specialist"}]} — exactly one critic subtask that '
    "depends on every other subtask, 2-5 subtasks total, no other roles."
)


class Planner:
    """Mission -> validated DAG, LLM-driven when live with heuristic fallback."""

    def __init__(self, llm: LLMClient, on_usage: Any | None = None) -> None:
        """Store the shared LLM client and an optional usage callback.

        Args:
            llm: the shared :class:`orchestrator.llm.LLMClient`.
            on_usage: optional ``callable(input_tokens, output_tokens)`` —
                the engine uses it to feed planner tokens into the cost meter.
        """
        self.llm = llm
        self.on_usage = on_usage

    async def plan(
        self,
        mission: str,
        template_id: str | None = None,
        dataset_columns: list[str] | None = None,
    ) -> Plan:
        """Produce a validated Plan for *mission*.

        Order of preference: marketplace template (when importable and the id
        matches) -> LLM plan (live mode only) -> heuristic plan. All paths end
        at the same validation contract.
        """
        mission = (mission or "").strip()
        if not mission:
            raise PlanValidationError("mission must be a non-empty string")

        if template_id:
            plan = template_plan(template_id, mission)
            if plan is not None:
                return plan
            logger.info("template %r unavailable; falling back", template_id)

        if not self.llm.is_mock:
            try:
                plan = await self._llm_plan(mission, template_id, dataset_columns)
                if plan is not None:
                    return plan
            except Exception as exc:  # noqa: BLE001 — any LLM failure falls back
                logger.warning("LLM planning failed (%s); using heuristic plan", exc)
        return heuristic_plan(mission, dataset_columns)

    async def _llm_plan(
        self,
        mission: str,
        template_id: str | None,
        dataset_columns: list[str] | None,
    ) -> Plan | None:
        """One strict JSON planning call, normalized and validated."""
        context = [f"MISSION: {mission}"]
        if template_id:
            context.append(f"TEMPLATE: {template_id}")
        if dataset_columns:
            context.append(f"DATASET COLUMNS: {', '.join(dataset_columns)}")
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the planner agent of an AgentForge team. ROLE: planner. "
                    "Decompose business missions into specialist subtasks as a DAG. "
                    "Allowed agents: researcher, analyst, forecaster, critic. "
                    "The critic must come last and depend on every other subtask."
                ),
            },
            {"role": "user", "content": "\n".join(context)},
        ]
        data = await self.llm.complete_json(
            messages,
            required_keys=["subtasks"],
            schema_hint=_LLM_PLAN_SCHEMA_HINT,
        )
        if self.on_usage is not None and self.llm.last_response is not None:
            usage = self.llm.last_response.usage
            self.on_usage(usage.input_tokens, usage.output_tokens)
        raw_subtasks = data.get("subtasks")
        if not isinstance(raw_subtasks, list) or not raw_subtasks:
            logger.warning("LLM plan has no subtasks list; rejecting")
            return None

        subtasks: list[Subtask] = []
        for index, node in enumerate(raw_subtasks, start=1):
            if not isinstance(node, dict):
                continue
            agent = str(node.get("agent") or "").strip().lower()
            if agent == "planner":  # planner never schedules itself
                agent = "researcher"
            subtasks.append(
                Subtask(
                    id=str(node.get("id") or f"t{index}").strip(),
                    title=str(node.get("title") or f"Subtask {index}"),
                    agent=agent or "researcher",
                    depends_on=[str(d) for d in node.get("depends_on", []) if str(d).strip()],
                    guidance=str(node.get("guidance") or ""),
                )
            )
        if not subtasks:
            return None

        plan = Plan(subtasks=subtasks, strategy="llm")
        plan.normalize()
        try:
            plan.validate()
        except PlanValidationError as exc:
            logger.warning("LLM plan failed validation (%s); rejecting", exc)
            return None
        return plan
