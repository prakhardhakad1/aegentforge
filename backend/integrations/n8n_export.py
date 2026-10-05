"""n8n workflow export for AgentForge runs (Agent 9, ForgeHacks 2026).

Contract (pinned in docs/INTERFACES.md)::

    from integrations.n8n_export import export_n8n
    workflow = export_n8n(run_snapshot)   # run_snapshot = GET /api/runs/{id} shape

The backend route ``POST /api/runs/{id}/export/n8n`` lazily imports this module
with ``cwd = backend/`` (so ``integrations`` is a top-level import root) and
returns the produced dict as an importable ``.json`` attachment.

--------------------------------------------------------------------------------
What the exported workflow is
--------------------------------------------------------------------------------
A one-click export turns a finished (or in-flight) AgentForge run into an n8n
workflow that *mirrors that run's plan DAG on the n8n canvas*:

    Webhook (path ``agentforge-run-{run_id}``)
      -> Set "Mission Context"                       (goal / ids / api_url)
      -> per plan subtask, in topological order:
             [NoOp "Join: ..." when the step has >= 2 dependencies]
           -> Set "Context [<agent>]: <title>"       (assembles step context)
           -> HTTP Request "Run Step [<agent>]: ..." (posts context to backend)
      -> IF "Critic Verdict"                         (after the critic step)
           true  -> Code "Assemble Report"
                      -> HTTP Request "Deliver Report"
           false -> NoOp "Flagged for Rework"         (rework extension point)

When the snapshot carries no usable ``plan_created`` event, the exporter falls
back to a linear pipeline: planner -> analyst -> critic -> report.

--------------------------------------------------------------------------------
URL honesty (no fabricated integrations)
--------------------------------------------------------------------------------
Every HTTP node URL targets the **AgentForge backend only**. There is no third-
party API, no invented SaaS endpoint, and no credential anywhere in the export.
URLs are always one of:

1. An env-substituted expression:
   ``={{ $env.AGENTFORGE_API_URL || 'http://agentforge-backend:8000' }}`` —
   set ``AGENTFORGE_API_URL`` inside n8n to point at your deployment. Note:
   ``$env`` works on self-hosted n8n; n8n Cloud blocks ``$env`` in
   expressions, so Cloud users substitute their literal URL (or an n8n
   Variable) for that fragment.
2. A ``{{ ... }}`` expression built from that same base URL.

Endpoint paths used:
- Steps:  ``POST {base}/api/runs/{run_id}/steps/{subtask_id}`` — the export's
  re-drive convention for executing one plan subtask with its context. The
  pinned v1 backend exposes run-level endpoints, so executing this scaffold
  step-by-step against a stock backend expects a thin step-endpoint shim (or
  repoint the URLs at your own workers inside n8n). This is documented, not
  hidden: the wiring, DAG shape, critic branch and report delivery are real.
- Report: ``POST {base}/api/runs/{run_id}/report`` — delivery of the assembled
  report back to the AgentForge backend. The pinned v1 API *serves* reports at
  ``GET /api/runs/{id}/report``; flip the method in n8n to GET to fetch the
  rendered report instead of POSTing one.

--------------------------------------------------------------------------------
Determinism
--------------------------------------------------------------------------------
The same ``run_snapshot`` always produces byte-identical JSON: node ids and
webhook ids are ``uuid5`` values derived from the run id + node name, positions
are computed deterministically from the DAG, and no wall-clock timestamp is
embedded anywhere (see ``meta``).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = ["export_n8n", "N8nExportError", "EXPORTER_VERSION"]


EXPORTER_VERSION = "1.0.0"

#: Deterministic namespace for node / webhook ids (same input -> same ids).
_UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "agentforge-n8n-export")

#: Default base URL used inside expressions when the n8n env var is unset.
DEFAULT_API_URL = "http://agentforge-backend:8000"

#: The exact expression every exported HTTP node URL is built from.
API_URL_EXPRESSION = (
    "={{ $env.AGENTFORGE_API_URL || 'http://agentforge-backend:8000' }}"
)

# ── Core n8n node types (only types that ship with n8n and import cleanly) ──
TYPE_WEBHOOK = "n8n-nodes-base.webhook"        # typeVersion 2
TYPE_HTTP_REQUEST = "n8n-nodes-base.httpRequest"  # typeVersion 4.2
TYPE_SET = "n8n-nodes-base.set"                # typeVersion 3.4
TYPE_CODE = "n8n-nodes-base.code"              # typeVersion 2
TYPE_IF = "n8n-nodes-base.if"                  # typeVersion 2.2
TYPE_NOOP = "n8n-nodes-base.noOp"              # typeVersion 1

ALLOWED_NODE_TYPES: frozenset[str] = frozenset(
    {TYPE_WEBHOOK, TYPE_HTTP_REQUEST, TYPE_SET, TYPE_CODE, TYPE_IF, TYPE_NOOP}
)

# Fixed node names used by expressions that cross-reference other nodes.
WEBHOOK_NODE_NAME = "Webhook Trigger"
MISSION_CONTEXT_NODE_NAME = "Mission Context"
IF_NODE_NAME = "Critic Verdict"
CODE_NODE_NAME = "Assemble Report"
DELIVER_NODE_NAME = "Deliver Report"
FLAGGED_NODE_NAME = "Flagged for Rework"
REPORT_JOIN_NODE_NAME = "Join: Report Inputs"

# Canvas geometry (left-to-right layout, n8n position units).
_COL_WIDTH = 220          # horizontal distance between chained nodes
_SUBTASK_STRIDE = 2 * _COL_WIDTH  # each subtask layer spans a Set + HTTP pair
_ROW_HEIGHT = 220         # vertical stagger between parallel branches
_X_WEBHOOK = 0
_X_MISSION_CONTEXT = _COL_WIDTH
_X_FIRST_SUBTASK_LAYER = 2 * _COL_WIDTH + 20


class N8nExportError(ValueError):
    """Raised when ``run_snapshot`` is fundamentally unusable.

    The backend route converts this into a clean JSON error response; the
    message is always safe to show (it never contains secrets). Degradable
    problems (missing plan, dangling dependencies, malformed events) do NOT
    raise — they fall back to the linear pipeline and are recorded in
    ``meta.plan_source`` / ``meta.plan_note``.
    """


@dataclass(frozen=True)
class Subtask:
    """One validated plan subtask extracted from a ``plan_created`` event."""

    id: str
    title: str
    agent: str
    depends_on: tuple[str, ...] = field(default=())


# ─────────────────────────────────────────────────────────────────────────────
# Small string / id helpers
# ─────────────────────────────────────────────────────────────────────────────


def _clean_label(text: Any, max_len: int = 48) -> str:
    """Collapse whitespace and truncate *text* for use in a node name."""
    collapsed = " ".join(str(text if text is not None else "").split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 3].rstrip() + "..."


def _js_quote(text: str) -> str:
    """Return *text* as a safe single-quoted JavaScript string literal.

    Used when baking AgentForge snapshot values (mission goal, ids) into n8n
    expressions as deterministic fallbacks.
    """
    escaped = (
        str(text)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return "'" + escaped + "'"


def _uuid_for(run_id: str, key: str) -> str:
    """Deterministic UUID string derived from the run id and a node key."""
    return str(uuid.uuid5(_UUID_NAMESPACE, f"{run_id}|{key}"))


def _sanitize_webhook_path(run_id: str) -> str:
    """Reduce a run id to a URL-safe webhook path fragment."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", str(run_id)).strip("-").lower()
    return safe or "unknown-run"


def _dedupe_name(base: str, used: set[str]) -> str:
    """Return *base*, or *base* with a numeric suffix if it was already used."""
    if base not in used:
        used.add(base)
        return base
    counter = 2
    while f"{base} ({counter})" in used:
        counter += 1
    final = f"{base} ({counter})"
    used.add(final)
    return final


# ─────────────────────────────────────────────────────────────────────────────
# Plan extraction (plan_created event -> validated subtask list)
# ─────────────────────────────────────────────────────────────────────────────


def _fallback_subtasks() -> list[Subtask]:
    """Linear fallback pipeline: planner -> analyst -> critic (report follows).

    The pinned agent roles also include researcher and forecaster; without a
    real plan we cannot know their subtasks, so the conservative fallback uses
    the three roles the brief pins for the linear pipeline, and the report
    delivery node completes the chain.
    """
    return [
        Subtask(id="st1", title="Plan the mission", agent="planner"),
        Subtask(id="st2", title="Analyze the data", agent="analyst", depends_on=("st1",)),
        Subtask(id="st3", title="Critique the findings", agent="critic", depends_on=("st2",)),
    ]


def _extract_subtasks(events: Any) -> tuple[list[Subtask], str, str | None]:
    """Extract the plan DAG from run events.

    Returns ``(subtasks, plan_source, plan_note)`` where ``plan_source`` is
    ``"plan_created"`` when a real plan was used, or ``"fallback_linear"``
    otherwise (with ``plan_note`` explaining why).
    """
    fallback = ("fallback_linear", None)

    if not isinstance(events, list):
        return _fallback_subtasks(), fallback[0], "run snapshot had no usable events list"

    best_seq = -1
    best_index = -1
    best_payload: dict[str, Any] | None = None
    for index, event in enumerate(events):
        if not isinstance(event, dict) or event.get("type") != "plan_created":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        seq = event.get("seq") if isinstance(event.get("seq"), int) else -1
        if best_payload is None or (seq, index) > (best_seq, best_index):
            best_seq, best_index, best_payload = seq, index, payload

    if best_payload is None:
        return _fallback_subtasks(), fallback[0], "no plan_created event found in run events"

    raw_subtasks = best_payload.get("subtasks")
    if not isinstance(raw_subtasks, list) or not raw_subtasks:
        return _fallback_subtasks(), fallback[0], "plan_created payload had no usable subtasks"

    # Pass 1 — collect valid, deduplicated ids so depends_on can be filtered.
    known_ids: list[str] = []
    seen_ids: set[str] = set()
    for item in raw_subtasks:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        subtask_id = raw_id.strip()
        suffix = 2
        while subtask_id in seen_ids:
            subtask_id = f"{raw_id.strip()}_dup{suffix}"
            suffix += 1
        seen_ids.add(subtask_id)
        known_ids.append(subtask_id)

    if not known_ids:
        return _fallback_subtasks(), fallback[0], "plan_created subtasks were all invalid"

    # Pass 2 — build Subtasks, keeping only deps that reference known ids.
    known_id_set = set(known_ids)
    subtasks: list[Subtask] = []
    cursor = 0
    for item in raw_subtasks:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        subtask_id = known_ids[cursor]
        cursor += 1

        title_raw = item.get("title")
        title = _clean_label(title_raw if isinstance(title_raw, str) and title_raw.strip() else subtask_id)

        agent_raw = item.get("agent")
        agent = agent_raw.strip() if isinstance(agent_raw, str) and agent_raw.strip() else "analyst"

        deps_raw = item.get("depends_on")
        deps: list[str] = []
        if isinstance(deps_raw, list):
            for dep in deps_raw:
                if isinstance(dep, str) and dep.strip() in known_id_set and dep.strip() != subtask_id:
                    dep_id = dep.strip()
                    if dep_id not in deps:
                        deps.append(dep_id)

        subtasks.append(Subtask(id=subtask_id, title=title, agent=agent, depends_on=tuple(deps)))

    if not subtasks:
        return _fallback_subtasks(), fallback[0], "plan_created subtasks were all invalid"

    return subtasks, "plan_created", None


def _topological_order(subtasks: list[Subtask]) -> list[Subtask] | None:
    """Deterministic topological sort (Kahn, smallest original index first).

    Returns ``None`` when the dependency graph contains a cycle (including a
    self-dependency) — callers fall back to the linear pipeline.
    """
    index_of = {subtask.id: position for position, subtask in enumerate(subtasks)}
    dependencies = {
        subtask.id: [dep for dep in subtask.depends_on if dep in index_of]
        for subtask in subtasks
    }
    dependents: dict[str, list[str]] = {subtask.id: [] for subtask in subtasks}
    indegree: dict[str, int] = {}
    for subtask in subtasks:
        indegree[subtask.id] = len(dependencies[subtask.id])
        for dep in dependencies[subtask.id]:
            dependents[dep].append(subtask.id)

    import heapq

    heap: list[int] = [index_of[subtask.id] for subtask in subtasks if indegree[subtask.id] == 0]
    heapq.heapify(heap)
    ordered: list[Subtask] = []
    while heap:
        position = heapq.heappop(heap)
        subtask = subtasks[position]
        ordered.append(subtask)
        for dependent_id in dependents[subtask.id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                heapq.heappush(heap, index_of[dependent_id])

    if len(ordered) != len(subtasks):
        return None
    return ordered


def _depths(order: list[Subtask]) -> dict[str, int]:
    """Longest-path depth per subtask (root steps are depth 0)."""
    depth: dict[str, int] = {}
    for subtask in order:  # topological order guarantees deps are seen first
        if not subtask.depends_on:
            depth[subtask.id] = 0
        else:
            depth[subtask.id] = 1 + max(depth[dep] for dep in subtask.depends_on)
    return depth


# ─────────────────────────────────────────────────────────────────────────────
# Node builders (each returns a complete n8n node dict)
# ─────────────────────────────────────────────────────────────────────────────


def _base_node(node_id: str, name: str, node_type: str, type_version: float, x: int, y: int) -> dict[str, Any]:
    return {
        "parameters": {},
        "id": node_id,
        "name": name,
        "type": node_type,
        "typeVersion": type_version,
        "position": [x, y],
    }


def _webhook_node(run_id: str, x: int, y: int) -> dict[str, Any]:
    """POST webhook that triggers the exported pipeline.

    ``responseMode: onReceived`` acknowledges immediately; the heavy work
    happens in the chained nodes.
    """
    node = _base_node(
        _uuid_for(run_id, WEBHOOK_NODE_NAME),
        WEBHOOK_NODE_NAME,
        TYPE_WEBHOOK,
        2,
        x,
        y,
    )
    node["webhookId"] = _uuid_for(run_id, f"{WEBHOOK_NODE_NAME}|webhookId")
    node["parameters"] = {
        "httpMethod": "POST",
        "path": f"agentforge-run-{_sanitize_webhook_path(run_id)}",
        "responseMode": "onReceived",
        "options": {},
    }
    return node


def _mission_context_node(run_id: str, goal: str, mission_id: str, template_id: str | None, x: int, y: int) -> dict[str, Any]:
    """Set node assembling the shared mission context from webhook body first,
    falling back to the values baked in at export time."""
    assignments: list[dict[str, Any]] = []

    def _add(name: str, expression: str, value_type: str = "string") -> None:
        assignments.append(
            {
                "id": _uuid_for(run_id, f"{MISSION_CONTEXT_NODE_NAME}|{name}"),
                "name": name,
                "value": expression,
                "type": value_type,
            }
        )

    _add(
        "run_id",
        "={{ $json.body && $json.body.run_id ? $json.body.run_id : " + _js_quote(run_id) + " }}",
    )
    _add(
        "mission_id",
        "={{ $json.body && $json.body.mission_id ? $json.body.mission_id : " + _js_quote(mission_id) + " }}",
    )
    _add(
        "goal",
        "={{ $json.body && $json.body.goal ? $json.body.goal : " + _js_quote(goal) + " }}",
    )
    _add(
        "template_id",
        "={{ $json.body && $json.body.template_id ? $json.body.template_id : " + _js_quote(template_id or "") + " }}",
    )
    _add("api_url", API_URL_EXPRESSION)

    node = _base_node(
        _uuid_for(run_id, MISSION_CONTEXT_NODE_NAME),
        MISSION_CONTEXT_NODE_NAME,
        TYPE_SET,
        3.4,
        x,
        y,
    )
    node["parameters"] = {
        "mode": "manual",
        "duplicateItem": False,
        "assignments": {"assignments": assignments},
        "includeOtherFields": False,
        "options": {},
    }
    return node


def _step_context_node(
    run_id: str,
    subtask: Subtask,
    name: str,
    x: int,
    y: int,
) -> dict[str, Any]:
    """Set node assembling one subtask's step context.

    Static plan fields are baked in at export time; run/mission fields and the
    API base URL come from the Mission Context node; ``upstream_outputs`` picks
    up whatever items arrived from the previous step (or the join NoOp).
    """
    prefix = f"step|{subtask.id}|context"
    assignments: list[dict[str, Any]] = []

    def _add(name_: str, value: str, value_type: str = "string") -> None:
        assignments.append(
            {
                "id": _uuid_for(run_id, f"{prefix}|{name_}"),
                "name": name_,
                "value": value,
                "type": value_type,
            }
        )

    _add("subtask_id", subtask.id)
    _add("subtask_title", subtask.title)
    _add("agent", subtask.agent)
    _add("depends_on", "[" + ", ".join(_js_quote(dep) for dep in subtask.depends_on) + "]" if subtask.depends_on else "[]")
    _add("run_id", "={{ $('" + MISSION_CONTEXT_NODE_NAME + "').first().json.run_id }}")
    _add("mission_id", "={{ $('" + MISSION_CONTEXT_NODE_NAME + "').first().json.mission_id }}")
    _add("goal", "={{ $('" + MISSION_CONTEXT_NODE_NAME + "').first().json.goal }}")
    _add("api_url", "={{ $('" + MISSION_CONTEXT_NODE_NAME + "').first().json.api_url }}")
    _add(
        "upstream_outputs",
        "={{ $input.all().map(function (item) { return item.json; }) }}",
        "array",
    )

    node = _base_node(_uuid_for(run_id, name), name, TYPE_SET, 3.4, x, y)
    node["parameters"] = {
        "mode": "manual",
        "duplicateItem": False,
        "assignments": {"assignments": assignments},
        "includeOtherFields": False,
        "options": {},
    }
    return node


def _run_step_node(run_id: str, subtask: Subtask, name: str, x: int, y: int) -> dict[str, Any]:
    """HTTP Request node executing one subtask against the AgentForge backend.

    The URL is an env-substituted AgentForge endpoint (see module docstring):
    ``POST {AGENTFORGE_API_URL}/api/runs/{run_id}/steps/{subtask_id}``. The
    full step context assembled by the preceding Set node is passed through as
    the JSON body.
    """
    node = _base_node(_uuid_for(run_id, name), name, TYPE_HTTP_REQUEST, 4.2, x, y)
    node["parameters"] = {
        "method": "POST",
        "url": "={{ $json.api_url }}/api/runs/{{ $json.run_id }}/steps/{{ $json.subtask_id }}",
        "sendBody": True,
        "contentType": "application/json",
        "specifyBody": "json",
        "jsonBody": "={{ $json }}",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "X-AgentForge-Subtask", "value": subtask.id},
                {"name": "X-AgentForge-Agent", "value": subtask.agent},
            ]
        },
        "options": {},
    }
    return node


def _join_node(run_id: str, name: str, x: int, y: int) -> dict[str, Any]:
    """NoOp join point where a step's multiple dependencies converge."""
    node = _base_node(_uuid_for(run_id, name), name, TYPE_NOOP, 1, x, y)
    node["parameters"] = {}
    return node


def _if_node(run_id: str, x: int, y: int) -> dict[str, Any]:
    """IF node implementing the critic verdict branch.

    Passes (true output) unless the critic step's response explicitly says
    ``approved === false``; the false output leads to the rework NoOp.
    """
    node = _base_node(_uuid_for(run_id, IF_NODE_NAME), IF_NODE_NAME, TYPE_IF, 2.2, x, y)
    node["parameters"] = {
        "conditions": {
            "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "loose",
            },
            "conditions": [
                {
                    "id": _uuid_for(run_id, f"{IF_NODE_NAME}|condition"),
                    "leftValue": "={{ $json.approved !== false }}",
                    "rightValue": "",
                    "operator": {
                        "type": "boolean",
                        "operation": "true",
                        "singleValue": True,
                    },
                }
            ],
            "combinator": "and",
        },
        "options": {},
    }
    return node


def _code_node(run_id: str, step_node_names: list[str], x: int, y: int) -> dict[str, Any]:
    """Code node merging every step's output into the report payload.

    The generated JS references each step HTTP node by name, so the report is
    assembled from the full plan even when the IF branch or join points mean a
    node's output does not flow into this node directly.
    """
    name_list_js = ",\n  ".join(_js_quote(name) for name in step_node_names)
    js_code = f"""// Assemble the AgentForge report payload from the completed step outputs.
// Each entry in step_node_names is an AgentForge step HTTP node; its response
// holds that subtask's result from the AgentForge backend.
var step_node_names = [
  {name_list_js}
];
var mission = $('{MISSION_CONTEXT_NODE_NAME}').first().json;
var steps = [];
for (var i = 0; i < step_node_names.length; i++) {{
  var node_name = step_node_names[i];
  var output = null;
  try {{
    output = $(node_name).first().json;
  }} catch (error) {{
    output = {{ error: 'no output from ' + node_name }};
  }}
  steps.push({{ node: node_name, data: output }});
}}
var report = {{
  run_id: mission.run_id,
  mission_id: mission.mission_id,
  goal: mission.goal,
  template_id: mission.template_id || null,
  step_count: steps.length,
  steps: steps,
  api_url: mission.api_url,
  source: 'agentforge-n8n-export'
}};
return [{{ json: report }}];
"""
    node = _base_node(_uuid_for(run_id, CODE_NODE_NAME), CODE_NODE_NAME, TYPE_CODE, 2, x, y)
    node["parameters"] = {
        "mode": "runOnceForAllItems",
        "jsCode": js_code,
    }
    return node


def _deliver_node(run_id: str, x: int, y: int) -> dict[str, Any]:
    """Final HTTP Request node POSTing the assembled report.

    Targets the AgentForge backend (env-substituted); see the module docstring
    for the GET-vs-POST note on the pinned report endpoint.
    """
    node = _base_node(_uuid_for(run_id, DELIVER_NODE_NAME), DELIVER_NODE_NAME, TYPE_HTTP_REQUEST, 4.2, x, y)
    node["parameters"] = {
        "method": "POST",
        "url": "={{ $json.api_url }}/api/runs/{{ $json.run_id }}/report",
        "sendBody": True,
        "contentType": "application/json",
        "specifyBody": "json",
        "jsonBody": "={{ $json }}",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "X-AgentForge-Kind", "value": "report"},
                {"name": "X-AgentForge-Source", "value": "n8n-export"},
            ]
        },
        "options": {},
    }
    return node


def _noop_node(run_id: str, name: str, x: int, y: int) -> dict[str, Any]:
    node = _base_node(_uuid_for(run_id, name), name, TYPE_NOOP, 1, x, y)
    node["parameters"] = {}
    return node


# ─────────────────────────────────────────────────────────────────────────────
# Connection assembly
# ─────────────────────────────────────────────────────────────────────────────


def _add_edge(connections: dict[str, Any], source: str, target: str, output_index: int = 0) -> None:
    """Append one main-connection edge, creating the n8n structure as needed.

    ``connections[source]["main"][output_index]`` is the list of targets for
    that output branch (n8n's expected main input/output structure). An IF node
    uses branch 0 for true and branch 1 for false; fan-out uses multiple
    entries inside a single branch.
    """
    node_connections = connections.setdefault(source, {"main": []})
    branches = node_connections["main"]
    while len(branches) <= output_index:
        branches.append([])
    branches[output_index].append({"node": target, "type": "main", "index": 0})


# ─────────────────────────────────────────────────────────────────────────────
# Public entrypoint
# ─────────────────────────────────────────────────────────────────────────────


def export_n8n(run_snapshot: dict) -> dict:
    """Convert an AgentForge run snapshot into an importable n8n workflow dict.

    Args:
        run_snapshot: The GET ``/api/runs/{id}`` response shape —
            ``{"run": {...}, "mission": {...}, "events": [Event envelopes],
            "artifacts": [...], "token_usage": {...}, "report"?: {...}}``.
            Extra keys are ignored; most malformed content degrades gracefully
            to the fallback pipeline (see ``meta.plan_source``).

    Returns:
        A dict of the form ``{"name", "nodes", "connections", "settings",
        "meta"}`` — the exact structure n8n's *Workflows -> Import from File /
        Import from JSON* accepts. Only core node types are used (Webhook,
        HTTP Request, Set, Code, IF, NoOp), every URL points at the
        AgentForge backend via ``$env.AGENTFORGE_API_URL`` expressions, and
        output is deterministic for identical input.

    Raises:
        N8nExportError: If ``run_snapshot`` is not a dict. Everything else is
            handled by degradation so the backend route never crashes.
    """
    if not isinstance(run_snapshot, dict):
        raise N8nExportError(
            "run_snapshot must be a dict matching the GET /api/runs/{id} response shape; "
            f"got {type(run_snapshot).__name__}"
        )

    run = run_snapshot.get("run") if isinstance(run_snapshot.get("run"), dict) else {}
    mission = run_snapshot.get("mission") if isinstance(run_snapshot.get("mission"), dict) else {}

    run_id = str(run.get("id") or "unknown-run")
    mission_id = str(mission.get("id") or run.get("mission_id") or "unknown-mission")
    goal_raw = mission.get("goal")
    goal = goal_raw if isinstance(goal_raw, str) and goal_raw.strip() else "AgentForge mission"
    template_raw = mission.get("template_id") or run.get("template_id")
    template_id = template_raw if isinstance(template_raw, str) and template_raw.strip() else None

    subtasks, plan_source, plan_note = _extract_subtasks(run_snapshot.get("events"))
    order = _topological_order(subtasks)
    if order is None:
        subtasks = _fallback_subtasks()
        plan_source = "fallback_linear"
        plan_note = "plan dependency graph contained a cycle; fell back to the linear pipeline"
        order = _topological_order(subtasks)
        if order is None:  # pragma: no cover - fallback plan is acyclic by construction
            raise N8nExportError("internal error: fallback pipeline failed topological sort")

    used_names: set[str] = set()
    nodes: list[dict[str, Any]] = []
    connections: dict[str, Any] = {}

    # ── Trigger + shared context ────────────────────────────────────────────
    webhook = _webhook_node(run_id, _X_WEBHOOK, 0)
    mission_context = _mission_context_node(run_id, goal, mission_id, template_id, _X_MISSION_CONTEXT, 0)
    nodes.extend([webhook, mission_context])
    _add_edge(connections, WEBHOOK_NODE_NAME, MISSION_CONTEXT_NODE_NAME)

    # ── Per-subtask chain mirroring the plan DAG ────────────────────────────
    depths = _depths(order)
    set_name_by_id: dict[str, str] = {}
    http_name_by_id: dict[str, str] = {}
    join_name_by_id: dict[str, str] = {}

    for subtask in order:
        depth = depths[subtask.id]
        base_x = _X_FIRST_SUBTASK_LAYER + depth * _SUBTASK_STRIDE
        set_name = _dedupe_name(f"Context [{subtask.agent}]: {subtask.title}", used_names)
        http_name = _dedupe_name(f"Run Step [{subtask.agent}]: {subtask.title}", used_names)
        set_name_by_id[subtask.id] = set_name
        http_name_by_id[subtask.id] = http_name

        if len(subtask.depends_on) >= 2:
            join_name = _dedupe_name(f"Join: {subtask.title}", used_names)
            join_name_by_id[subtask.id] = join_name
            join_node = _join_node(run_id, join_name, base_x - 140, 0)
            nodes.append(join_node)
            for dep in subtask.depends_on:
                _add_edge(connections, http_name_by_id[dep], join_name)
            _add_edge(connections, join_name, set_name)

        context_node = _step_context_node(run_id, subtask, set_name, base_x, 0)
        step_node = _run_step_node(run_id, subtask, http_name, base_x + _COL_WIDTH, 0)
        nodes.extend([context_node, step_node])

        if not subtask.depends_on:
            _add_edge(connections, MISSION_CONTEXT_NODE_NAME, set_name)
        elif len(subtask.depends_on) == 1:
            _add_edge(connections, http_name_by_id[subtask.depends_on[0]], set_name)

    # Layout pass — stagger Y per layer now that layer sizes are known, so
    # parallel branches fan out vertically instead of overlapping.
    layer_members: dict[int, list[str]] = {}
    for subtask in order:
        layer_members.setdefault(depths[subtask.id], []).append(subtask.id)
    position_by_name: dict[str, list[int]] = {}
    for depth, member_ids in layer_members.items():
        count = len(member_ids)
        base_x = _X_FIRST_SUBTASK_LAYER + depth * _SUBTASK_STRIDE
        for slot, member_id in enumerate(member_ids):
            y = int(round((slot - (count - 1) / 2) * _ROW_HEIGHT))
            position_by_name[set_name_by_id[member_id]] = [base_x, y]
            position_by_name[http_name_by_id[member_id]] = [base_x + _COL_WIDTH, y]
            if member_id in join_name_by_id:
                position_by_name[join_name_by_id[member_id]] = [base_x - 140, y]
    for node in nodes:
        if node["name"] in position_by_name:
            node["position"] = list(position_by_name[node["name"]])

    # ── Critic verdict branch + report assembly + delivery ──────────────────
    order_index = {subtask.id: position for position, subtask in enumerate(order)}
    critic_ids = [subtask.id for subtask in order if subtask.agent == "critic"]
    critic_id = (
        max(critic_ids, key=lambda sid: (depths[sid], order_index[sid])) if critic_ids else None
    )
    critic_http_name = http_name_by_id[critic_id] if critic_id is not None else None

    max_step_x = max(node["position"][0] for node in nodes)
    chain_x = int(max_step_x) + 2 * _COL_WIDTH

    step_node_names = [http_name_by_id[subtask.id] for subtask in order]
    code_node = _code_node(run_id, step_node_names, chain_x + _COL_WIDTH, 0)
    deliver_node = _deliver_node(run_id, chain_x + 2 * _COL_WIDTH, 0)

    if critic_http_name is not None:
        if_node = _if_node(run_id, chain_x, 0)
        flagged_node = _noop_node(run_id, FLAGGED_NODE_NAME, chain_x + _COL_WIDTH, _ROW_HEIGHT)
        nodes.extend([if_node, flagged_node, code_node, deliver_node])
        _add_edge(connections, critic_http_name, IF_NODE_NAME)
        _add_edge(connections, IF_NODE_NAME, CODE_NODE_NAME, output_index=0)   # true branch
        _add_edge(connections, IF_NODE_NAME, FLAGGED_NODE_NAME, output_index=1)  # false branch
        _add_edge(connections, CODE_NODE_NAME, DELIVER_NODE_NAME)
    else:
        # No critic step: terminal steps (nothing depends on them) converge on
        # the report assembler.
        depended_on = {dep for subtask in subtasks for dep in subtask.depends_on}
        terminal_names = [
            http_name_by_id[subtask.id]
            for subtask in order
            if subtask.id not in depended_on
        ]
        if len(terminal_names) >= 2:
            report_join = _join_node(run_id, REPORT_JOIN_NODE_NAME, chain_x, 0)
            nodes.extend([report_join, code_node, deliver_node])
            for terminal_name in terminal_names:
                _add_edge(connections, terminal_name, REPORT_JOIN_NODE_NAME)
            _add_edge(connections, REPORT_JOIN_NODE_NAME, CODE_NODE_NAME)
        else:
            nodes.extend([code_node, deliver_node])
            for terminal_name in terminal_names:
                _add_edge(connections, terminal_name, CODE_NODE_NAME)
        _add_edge(connections, CODE_NODE_NAME, DELIVER_NODE_NAME)

    edge_count = sum(
        len(targets)
        for node_connections in connections.values()
        for targets in node_connections["main"]
    )

    workflow_name = f"AgentForge Run {run_id} — {_clean_label(goal, 60)}"
    workflow: dict[str, Any] = {
        "name": workflow_name,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "meta": {
            "source": "agentforge",
            "exporter": "agentforge.integrations.n8n_export",
            "exporter_version": EXPORTER_VERSION,
            "agentforge_run_id": run_id,
            "agentforge_mission_id": mission_id,
            "agentforge_template_id": template_id,
            "plan_source": plan_source,
            "plan_note": plan_note,
            "subtask_count": len(subtasks),
            "node_count": len(nodes),
            "edge_count": edge_count,
            "api_url_expression": API_URL_EXPRESSION,
            "honesty_note": (
                "All HTTP nodes target the AgentForge backend via $env.AGENTFORGE_API_URL. "
                "No third-party APIs and no credentials are embedded."
            ),
        },
    }
    return workflow
