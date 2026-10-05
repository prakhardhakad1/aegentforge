"""orchestrator.templates.registry — marketplace template registry (Agent 8).

Holds the three pinned marketplace templates and the helpers other modules
consume:

- ``TEMPLATES`` / ``TEMPLATE_IDS`` / ``TEMPLATES_BY_ID`` — the registry.
- ``get_template(template_id)`` — lookup with a helpful ``KeyError``; this is
  the entrypoint the orchestrator engine/planner uses defensively.
- ``as_api_shape(template)`` — deep copy with exactly the pinned Template keys
  for the backend's ``GET /api/templates``.
- ``validate_all()`` / ``validate_template(template)`` — assert the pinned
  shape, unique ids, valid roles, acyclic DAGs with existing ``depends_on``,
  exactly one critic per team, and non-trivial prompts.
- ``is_dag_acyclic(nodes)`` / ``dag_problems(nodes)`` — DAG utilities.

Import discipline: this subpackage must NEVER import the orchestrator core
(stdlib only at runtime) and must have NO import-time side effects, so the
engine can ``import orchestrator.templates`` defensively without risk.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from orchestrator.templates._types import TemplateDict
from orchestrator.templates.market_research import MARKET_RESEARCH_TEAM
from orchestrator.templates.sales_insights import SALES_INSIGHTS_TEAM
from orchestrator.templates.support_triage import SUPPORT_TRIAGE_TEAM

__all__ = [
    "DAG_NODE_KEYS",
    "PINNED_ROLES",
    "TEAM_MEMBER_KEYS",
    "TEMPLATE_IDS",
    "TEMPLATE_KEYS",
    "TEMPLATES",
    "TEMPLATES_BY_ID",
    "as_api_shape",
    "dag_problems",
    "get_template",
    "is_dag_acyclic",
    "validate_all",
    "validate_template",
]

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TEMPLATES: list[TemplateDict] = [
    MARKET_RESEARCH_TEAM,
    SALES_INSIGHTS_TEAM,
    SUPPORT_TRIAGE_TEAM,
]
"""The three pinned marketplace templates, in pinned order."""

TEMPLATE_IDS: tuple[str, ...] = tuple(template["id"] for template in TEMPLATES)
"""Exact pinned template ids, in pinned order."""

TEMPLATES_BY_ID: dict[str, TemplateDict] = {
    template["id"]: template for template in TEMPLATES
}
"""Id -> template lookup; mirrors ``TEMPLATES``."""

# ---------------------------------------------------------------------------
# Pinned-shape constants
# ---------------------------------------------------------------------------

PINNED_ROLES: frozenset[str] = frozenset(
    {"planner", "researcher", "analyst", "forecaster", "critic"}
)
"""Exact agent role strings allowed in ``team[].role`` and DAG ``agent``."""

TEMPLATE_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "description",
        "tags",
        "team",
        "planner_prompt",
        "sample_mission",
        "expected_dag",
        "report_outline",
    }
)
"""Exactly the keys of the pinned Template shape (docs/INTERFACES.md)."""

TEAM_MEMBER_KEYS: frozenset[str] = frozenset({"role", "title", "system_prompt"})
"""Exactly the keys of a pinned ``team`` member."""

DAG_NODE_KEYS: frozenset[str] = frozenset({"id", "title", "agent", "depends_on"})
"""Exactly the keys of a pinned ``expected_dag`` node."""

MIN_SYSTEM_PROMPT_CHARS: int = 200
"""Floor for every member ``system_prompt`` — prompts are judged content."""

MIN_PLANNER_PROMPT_CHARS: int = 200
"""Floor for every template ``planner_prompt``."""


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def get_template(template_id: str) -> TemplateDict:
    """Return the marketplace template registered under ``template_id``.

    This is the defensive entrypoint the orchestrator engine/planner calls.

    Args:
        template_id: One of the pinned ids (``market_research_team``,
            ``sales_insights_team``, ``support_triage_team``).

    Returns:
        The matching template dict (pinned shape; shared registry object —
        treat as read-only, or use :func:`as_api_shape` for a deep copy).

    Raises:
        KeyError: With a message naming the unknown id and every available id.
    """
    template = TEMPLATES_BY_ID.get(template_id)
    if template is None:
        available = ", ".join(sorted(TEMPLATES_BY_ID)) or "(none registered)"
        raise KeyError(
            f"Unknown template id {template_id!r}. Available templates: {available}. "
            f"Expected one of the pinned marketplace ids."
        )
    return template


def as_api_shape(template: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep-copied dict with exactly the pinned Template keys.

    Built for the backend's ``GET /api/templates`` handler: extra keys on the
    input (if any) are dropped, nested team members and DAG nodes are narrowed
    to their pinned keys, and the result is deep-copied so callers can never
    mutate the registry.

    Args:
        template: A template dict (pinned shape).

    Returns:
        A fresh ``dict`` with exactly: ``id``, ``name``, ``description``,
        ``tags``, ``team`` ([{role, title, system_prompt}]),
        ``planner_prompt``, ``sample_mission``, ``expected_dag``
        ([{id, title, agent, depends_on}]), ``report_outline``.

    Raises:
        ValueError: If a pinned key (top level, team member, or DAG node) is
            missing from the input.
    """
    context = f"template {template.get('id', '<unknown>')!r}"
    shape: dict[str, Any] = {
        "id": _required(template, "id", context),
        "name": _required(template, "name", context),
        "description": _required(template, "description", context),
        "tags": list(_required(template, "tags", context)),
        "team": [
            {
                "role": _required(member, "role", f"{context} team member {index}"),
                "title": _required(member, "title", f"{context} team member {index}"),
                "system_prompt": _required(
                    member, "system_prompt", f"{context} team member {index}"
                ),
            }
            for index, member in enumerate(_required(template, "team", context))
        ],
        "planner_prompt": _required(template, "planner_prompt", context),
        "sample_mission": _required(template, "sample_mission", context),
        "expected_dag": [
            {
                "id": _required(node, "id", f"{context} dag node {index}"),
                "title": _required(node, "title", f"{context} dag node {index}"),
                "agent": _required(node, "agent", f"{context} dag node {index}"),
                "depends_on": list(
                    _required(node, "depends_on", f"{context} dag node {index}")
                ),
            }
            for index, node in enumerate(_required(template, "expected_dag", context))
        ],
        "report_outline": list(_required(template, "report_outline", context)),
    }
    return copy.deepcopy(shape)


def _required(mapping: Mapping[str, Any], key: str, context: str) -> Any:
    """Read a required key from ``mapping`` or raise a helpful ``ValueError``."""
    try:
        return mapping[key]
    except KeyError as exc:
        raise ValueError(f"{context} is missing required key {key!r}") from exc


# ---------------------------------------------------------------------------
# DAG utilities
# ---------------------------------------------------------------------------


def is_dag_acyclic(nodes: Sequence[Mapping[str, Any]]) -> bool:
    """Return ``True`` when ``nodes`` form a well-formed, acyclic task graph.

    Edges run from a node to its ``depends_on`` entries. Dependencies on ids
    not present in ``nodes`` are treated as satisfied external inputs (they
    cannot form a cycle here; use :func:`dag_problems` to detect them).
    Duplicate or empty node ids make the graph malformed and yield ``False``.

    Args:
        nodes: Sequence of mappings each carrying ``id`` and ``depends_on``.

    Returns:
        ``True`` if every node is reachable from the zero-indegree roots by
        Kahn's algorithm (i.e. no cycle), ``False`` otherwise.
    """
    adjacency: dict[str, list[str]] = {}
    for node in nodes:
        node_id = str(node.get("id", ""))
        if not node_id or node_id in adjacency:
            return False
        depends = node.get("depends_on") or []
        adjacency[node_id] = [str(dep) for dep in depends]

    # Kahn's algorithm over edges dep -> node (a node becomes ready once every
    # known dependency has been processed). Unknown dependencies are ignored:
    # they cannot contribute to a cycle.
    indegree: dict[str, int] = {node_id: 0 for node_id in adjacency}
    dependents: dict[str, list[str]] = {node_id: [] for node_id in adjacency}
    for node_id, deps in adjacency.items():
        for dep in deps:
            if dep in indegree:
                indegree[node_id] += 1
                dependents[dep].append(node_id)

    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    processed = 0
    while ready:
        current = ready.pop()
        processed += 1
        for dependent in dependents[current]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    return processed == len(adjacency)


def dag_problems(nodes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return every structural problem in a candidate ``expected_dag`` list.

    Checks: non-empty node ids, unique node ids, ``depends_on`` entries all
    referencing existing node ids, and acyclicity. An empty problem list means
    the DAG is structurally valid.

    Args:
        nodes: Sequence of mappings each carrying ``id`` and ``depends_on``.

    Returns:
        Human-readable problem strings; empty when the DAG is valid.
    """
    problems: list[str] = []
    ids: list[str] = []
    ids_well_formed = True
    for node in nodes:
        node_id = str(node.get("id", ""))
        if not node_id.strip():
            problems.append("a DAG node has an empty id")
            ids_well_formed = False
        elif node_id in ids:
            problems.append(f"duplicate DAG node id {node_id!r}")
            ids_well_formed = False
        ids.append(node_id)

    known = set(ids)
    for node in nodes:
        node_id = str(node.get("id", ""))
        for dep in node.get("depends_on") or []:
            if str(dep) not in known:
                problems.append(
                    f"DAG node {node_id!r} depends on unknown node {str(dep)!r}"
                )

    # Cycle check: only meaningful when ids are well-formed, since duplicate
    # or empty ids make is_dag_acyclic report "malformed" rather than cyclic.
    if ids_well_formed and not is_dag_acyclic(nodes):
        problems.append("DAG contains a cycle")
    return problems


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_all() -> list[str]:
    """Validate every registered template; return the validated ids in order.

    Asserts, for each template: the exact pinned shape, non-trivial strings,
    pinned roles only, exactly one critic per team, acyclic DAGs whose
    ``depends_on`` entries all exist, and non-empty ``sample_mission``. Also
    asserts registry-level uniqueness of template ids.

    Returns:
        The list of validated template ids, in pinned order.

    Raises:
        ValueError: With every problem found, joined into one message.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for template in TEMPLATES:
        if not isinstance(template, Mapping):
            problems.append("a registry entry is not a mapping")
            continue
        template_id = template.get("id")
        if not isinstance(template_id, str) or not template_id.strip():
            problems.append("a template has a missing or empty id")
            continue
        if template_id in seen:
            problems.append(f"duplicate template id {template_id!r}")
        seen.add(template_id)
    if problems:
        raise ValueError("template registry invalid: " + "; ".join(problems))

    for template in TEMPLATES:
        validate_template(template)
    return [template["id"] for template in TEMPLATES]


def validate_template(template: Mapping[str, Any]) -> None:
    """Validate one template against the pinned shape; raise on any problem.

    Args:
        template: The template dict to validate.

    Raises:
        ValueError: If the shape, roles, team composition, DAG, or prompt
            floors are violated. The message names the template id and every
            problem found.
    """
    problems: list[str] = []
    template_id = template.get("id") if isinstance(template, Mapping) else None
    label = f"template {template_id!r}" if isinstance(template_id, str) else "template"

    if not isinstance(template, Mapping):
        raise ValueError(f"{label} is not a mapping (got {type(template).__name__})")

    keys = set(template.keys())
    missing = sorted(TEMPLATE_KEYS - keys)
    extra = sorted(keys - TEMPLATE_KEYS)
    if missing:
        problems.append(f"missing pinned keys: {', '.join(missing)}")
    if extra:
        problems.append(f"unexpected extra keys: {', '.join(extra)}")

    problems.extend(_validate_strings(template, label))
    problems.extend(_validate_tags(template, label))
    problems.extend(_validate_team(template, label))
    problems.extend(_validate_dag(template, label))
    problems.extend(_validate_outline(template, label))

    if problems:
        raise ValueError(f"{label} is invalid: " + "; ".join(problems))


def _validate_strings(template: Mapping[str, Any], label: str) -> list[str]:
    """Validate the plain-string fields of a template."""
    problems: list[str] = []
    for key in ("id", "name", "description", "planner_prompt", "sample_mission"):
        value = template.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{key} must be a non-empty string")
    planner_prompt = template.get("planner_prompt")
    if (
        isinstance(planner_prompt, str)
        and len(planner_prompt) < MIN_PLANNER_PROMPT_CHARS
    ):
        problems.append(
            f"planner_prompt too short ({len(planner_prompt)} chars, "
            f"minimum {MIN_PLANNER_PROMPT_CHARS})"
        )
    return problems


def _validate_tags(template: Mapping[str, Any], label: str) -> list[str]:
    """Validate that ``tags`` is a non-empty list of non-empty strings."""
    problems: list[str] = []
    tags = template.get("tags")
    if not isinstance(tags, list) or not tags:
        problems.append("tags must be a non-empty list")
    elif not all(isinstance(tag, str) and tag.strip() for tag in tags):
        problems.append("every tag must be a non-empty string")
    return problems


def _validate_team(template: Mapping[str, Any], label: str) -> list[str]:
    """Validate team members: shape, roles, prompts, and the one-critic rule."""
    problems: list[str] = []
    team = template.get("team")
    if not isinstance(team, list) or not team:
        return ["team must be a non-empty list"]

    critic_count = 0
    roles: set[str] = set()
    for index, member in enumerate(team):
        if not isinstance(member, Mapping):
            problems.append(f"team member {index} is not a mapping")
            continue
        member_keys = set(member.keys())
        if member_keys != TEAM_MEMBER_KEYS:
            problems.append(
                f"team member {index} keys must be exactly "
                f"{sorted(TEAM_MEMBER_KEYS)}, got {sorted(member_keys)}"
            )
        role = member.get("role")
        if not isinstance(role, str) or role not in PINNED_ROLES:
            problems.append(
                f"team member {index} has invalid role {role!r} "
                f"(allowed: {sorted(PINNED_ROLES)})"
            )
            continue
        roles.add(role)
        if role == "critic":
            critic_count += 1
        title = member.get("title")
        if not isinstance(title, str) or not title.strip():
            problems.append(f"team member {index} ({role}) needs a non-empty title")
        system_prompt = member.get("system_prompt")
        if not isinstance(system_prompt, str):
            problems.append(
                f"team member {index} ({role}) needs a string system_prompt"
            )
        elif len(system_prompt) < MIN_SYSTEM_PROMPT_CHARS:
            problems.append(
                f"team member {index} ({role}) system_prompt too short "
                f"({len(system_prompt)} chars, minimum {MIN_SYSTEM_PROMPT_CHARS})"
            )

    if critic_count != 1:
        problems.append(
            f"team must have exactly one critic member, found {critic_count}"
        )
    return problems


def _validate_dag(template: Mapping[str, Any], label: str) -> list[str]:
    """Validate the expected DAG: shape, roles, references, acyclicity."""
    problems: list[str] = []
    dag = template.get("expected_dag")
    if not isinstance(dag, list) or not dag:
        return ["expected_dag must be a non-empty list"]

    team = template.get("team")
    team_roles: set[str] = set()
    if isinstance(team, list):
        team_roles = {
            member["role"] for member in team if isinstance(member, Mapping)
        }

    for index, node in enumerate(dag):
        if not isinstance(node, Mapping):
            problems.append(f"expected_dag node {index} is not a mapping")
            continue
        node_keys = set(node.keys())
        if node_keys != DAG_NODE_KEYS:
            problems.append(
                f"expected_dag node {index} keys must be exactly "
                f"{sorted(DAG_NODE_KEYS)}, got {sorted(node_keys)}"
            )
        agent = node.get("agent")
        if not isinstance(agent, str) or agent not in PINNED_ROLES:
            problems.append(
                f"expected_dag node {index} has invalid agent {agent!r} "
                f"(allowed: {sorted(PINNED_ROLES)})"
            )
        elif team_roles and agent not in team_roles:
            problems.append(
                f"expected_dag node {index} uses agent {agent!r} which is not "
                f"in the team roles {sorted(team_roles)}"
            )
        title = node.get("title")
        if not isinstance(title, str) or not title.strip():
            problems.append(f"expected_dag node {index} needs a non-empty title")
        depends_on = node.get("depends_on")
        if not isinstance(depends_on, list) or not all(
            isinstance(dep, str) for dep in depends_on
        ):
            problems.append(
                f"expected_dag node {index} depends_on must be a list of strings"
            )

    problems.extend(dag_problems(dag))

    # Engine-compatibility rules (orchestrator.planner.Plan.validate): the plan
    # must contain exactly one critic subtask, and nothing may run after the
    # critic except the engine's own revision slot — which templates cannot
    # express, so no template DAG node may depend on the critic.
    critic_ids = [str(node.get("id", "")) for node in dag if node.get("agent") == "critic"]
    if len(critic_ids) != 1:
        problems.append(
            f"expected_dag must contain exactly one critic node, found {len(critic_ids)}"
        )
    else:
        critic_id = critic_ids[0]
        for node in dag:
            if critic_id in (node.get("depends_on") or []):
                problems.append(
                    f"expected_dag node {node.get('id')!r} depends on the critic "
                    f"{critic_id!r}; only the engine's revision slot may follow "
                    "the critic, so the critic must be the final node"
                )
    return problems


def _validate_outline(template: Mapping[str, Any], label: str) -> list[str]:
    """Validate that ``report_outline`` is a non-empty list of non-empty strings."""
    problems: list[str] = []
    outline = template.get("report_outline")
    if not isinstance(outline, list) or not outline:
        problems.append("report_outline must be a non-empty list")
    elif not all(isinstance(section, str) and section.strip() for section in outline):
        problems.append("every report_outline entry must be a non-empty string")
    return problems
