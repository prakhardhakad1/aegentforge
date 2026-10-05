"""Tests for integrations.n8n_export (Agent 9).

Run from the repo root::

    python -m pytest backend/integrations/tests -q

or from ``backend/``::

    python -m pytest integrations/tests -q

Covers: valid workflow structure, connection-graph integrity, DAG edges that
mirror the plan subtasks, the linear fallback pipeline, determinism, URL
honesty (AgentForge-backend-only endpoints), and clean degradation on
malformed snapshots.
"""

from __future__ import annotations

import copy
import json

import pytest

from integrations.n8n_export import (
    API_URL_EXPRESSION,
    DEFAULT_API_URL,
    N8nExportError,
    export_n8n,
)

# ── Constants mirrored from the pinned interfaces ───────────────────────────

ALLOWED_NODE_TYPES = {
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.set",
    "n8n-nodes-base.code",
    "n8n-nodes-base.if",
    "n8n-nodes-base.noOp",
}

RUN_ID = "run-2026-market-01"
MISSION_ID = "mission-2026-market-01"
TEMPLATE_ID = "market_research_team"

# Market-research style plan (fan-out + fan-in + critic), mirroring the
# template's expected_dag shape from GET /api/templates.
MARKET_SUBTASKS = [
    {"id": "st1", "title": "Frame the research questions and plan", "agent": "planner", "depends_on": []},
    {"id": "st2", "title": "Gather market and competitor context", "agent": "researcher", "depends_on": ["st1"]},
    {"id": "st3", "title": "Profile the dataset and extract trends", "agent": "analyst", "depends_on": ["st1"]},
    {"id": "st4", "title": "Project demand trend for the next period", "agent": "forecaster", "depends_on": ["st3"]},
    {"id": "st5", "title": "Stress-test claims and rank recommendations", "agent": "critic", "depends_on": ["st2", "st3", "st4"]},
]


def _event(event_type: str, seq: int, agent: str | None, payload: dict) -> dict:
    """Build a pinned Event envelope."""
    return {
        "type": event_type,
        "run_id": RUN_ID,
        "seq": seq,
        "ts": f"2026-10-05T12:00:{seq:02d}Z",
        "agent": agent,
        "payload": payload,
    }


def _market_snapshot() -> dict:
    """Full GET /api/runs/{id}-shaped snapshot with a 5-subtask plan DAG."""
    return {
        "run": {
            "id": RUN_ID,
            "mission_id": MISSION_ID,
            "status": "succeeded",
            "created_at": "2026-10-05T12:00:00Z",
            "finished_at": "2026-10-05T12:04:31Z",
            "mode": "demo",
            "template_id": TEMPLATE_ID,
            "error": None,
            "error_stage": None,
        },
        "mission": {
            "id": MISSION_ID,
            "goal": "Assess demand for a subscription meal-planning app in mid-size US cities",
            "template_id": TEMPLATE_ID,
            "dataset_id": None,
            "created_at": "2026-10-05T11:59:00Z",
        },
        "events": [
            _event("run_started", 1, None, {"mode": "demo"}),
            _event("plan_created", 2, "planner", {"subtasks": copy.deepcopy(MARKET_SUBTASKS)}),
            _event("agent_started", 3, "planner", {"subtask_id": "st1", "title": MARKET_SUBTASKS[0]["title"]}),
            _event("thought_summary", 4, "planner", {"subtask_id": "st1", "summary": "Splitting into research, analysis, forecast, critique."}),
            _event("agent_finished", 5, "planner", {"subtask_id": "st1"}),
            _event("artifact_created", 6, "analyst", {"subtask_id": "st3", "artifact_id": "art1", "kind": "table", "name": "trend_table", "summary": "MoM demand trend"}),
            _event("token_update", 7, "analyst", {"agent": "analyst", "input_tokens": 1200, "output_tokens": 340, "cost_usd": 0.0001694, "run_total_usd": 0.0001694}),
            _event("run_finished", 8, None, {"report_ready": True}),
        ],
        "artifacts": [
            {"id": "art1", "run_id": RUN_ID, "subtask_id": "st3", "kind": "table", "name": "trend_table", "summary": "MoM demand trend", "path": None, "payload": {}, "created_at": "2026-10-05T12:02:00Z"}
        ],
        "token_usage": {
            "per_agent": {"planner": {"input_tokens": 800, "output_tokens": 210, "cost_usd": 0.0001111}},
            "totals": {"input_tokens": 2000, "output_tokens": 550, "cost_usd": 0.0002805},
        },
        "report": {"title": "Meal-planning app demand assessment", "mission": "Assess demand...", "style": "market_research"},
    }


def _edge_triples(workflow: dict) -> list[tuple[str, str, int]]:
    """Flatten connections into (source_name, target_name, branch_index)."""
    triples: list[tuple[str, str, int]] = []
    for source, node_connections in workflow["connections"].items():
        for branch_index, branch in enumerate(node_connections["main"]):
            for edge in branch:
                triples.append((source, edge["node"], branch_index))
    return triples


def _node_by_name(workflow: dict, name: str) -> dict | None:
    for node in workflow["nodes"]:
        if node["name"] == name:
            return node
    return None


def _nodes_of_type(workflow: dict, node_type: str) -> list[dict]:
    return [node for node in workflow["nodes"] if node["type"] == node_type]


def _step_names(subtasks: list[dict]) -> tuple[list[str], list[str]]:
    """Expected Set/HTTP node names for a plan (titles short enough to avoid
    truncation)."""
    set_names = [f"Context [{s['agent']}]: {s['title']}" for s in subtasks]
    http_names = [f"Run Step [{s['agent']}]: {s['title']}" for s in subtasks]
    return set_names, http_names


# ── 1. Valid workflow structure on a full planned run ───────────────────────


def test_valid_structure_full_plan() -> None:
    workflow = export_n8n(_market_snapshot())

    assert set(workflow) >= {"name", "nodes", "connections", "meta"}
    assert isinstance(workflow["name"], str) and workflow["name"]
    assert workflow["nodes"], "workflow must contain nodes"
    assert isinstance(workflow["connections"], dict)
    assert workflow["settings"]["executionOrder"] == "v1"

    names = [node["name"] for node in workflow["nodes"]]
    assert len(names) == len(set(names)), "node names must be unique"

    for node in workflow["nodes"]:
        assert node["id"], "each node needs an id"
        assert node["type"] in ALLOWED_NODE_TYPES, f"non-core node type: {node['type']}"
        assert isinstance(node["typeVersion"], (int, float))
        assert isinstance(node["position"], list) and len(node["position"]) == 2
        assert all(isinstance(v, (int, float)) for v in node["position"])

    # Webhook trigger with the pinned path convention.
    webhooks = _nodes_of_type(workflow, "n8n-nodes-base.webhook")
    assert len(webhooks) == 1
    assert webhooks[0]["parameters"]["path"] == f"agentforge-run-{RUN_ID}"
    assert webhooks[0]["parameters"]["httpMethod"] == "POST"
    assert webhooks[0]["webhookId"]

    # One step HTTP node per subtask + the final deliver node.
    http_nodes = _nodes_of_type(workflow, "n8n-nodes-base.httpRequest")
    assert len(http_nodes) == len(MARKET_SUBTASKS) + 1

    # One step context Set node per subtask + the Mission Context node.
    set_nodes = _nodes_of_type(workflow, "n8n-nodes-base.set")
    assert len(set_nodes) == len(MARKET_SUBTASKS) + 1

    # Critic verdict branch and the rework extension point exist.
    assert _nodes_of_type(workflow, "n8n-nodes-base.if")
    assert _node_by_name(workflow, "Flagged for Rework") is not None
    # st5 has three dependencies -> a NoOp join point must exist.
    assert _nodes_of_type(workflow, "n8n-nodes-base.noOp")

    # Meta reflects the real plan source.
    meta = workflow["meta"]
    assert meta["plan_source"] == "plan_created"
    assert meta["subtask_count"] == len(MARKET_SUBTASKS)
    assert meta["agentforge_run_id"] == RUN_ID
    assert meta["node_count"] == len(workflow["nodes"])

    # JSON round-trip (what the backend route ships to the client).
    assert json.loads(json.dumps(workflow)) == workflow


def test_all_connection_endpoints_exist() -> None:
    workflow = export_n8n(_market_snapshot())
    names = {node["name"] for node in workflow["nodes"]}
    for source, target, _branch in _edge_triples(workflow):
        assert source in names, f"connection source '{source}' is not a node"
        assert target in names, f"connection target '{target}' is not a node"
    assert _edge_triples(workflow), "workflow must have connections"


def test_dag_edges_match_plan_subtasks() -> None:
    """Every plan dependency becomes a real edge: dep HTTP -> (join ->) target Set."""
    workflow = export_n8n(_market_snapshot())
    edges = {(src, tgt) for src, tgt, _ in _edge_triples(workflow)}
    set_names, http_names = _step_names(MARKET_SUBTASKS)

    for subtask in MARKET_SUBTASKS:
        target_set = f"Context [{subtask['agent']}]: {subtask['title']}"
        assert target_set in set_names
        if not subtask["depends_on"]:
            assert (workflow["connections"]["Webhook Trigger"] is not None)
            assert ("Mission Context", target_set) in edges
        elif len(subtask["depends_on"]) == 1:
            dep_http = f"Run Step [{next(s['agent'] for s in MARKET_SUBTASKS if s['id'] == subtask['depends_on'][0])}]: " \
                f"{next(s['title'] for s in MARKET_SUBTASKS if s['id'] == subtask['depends_on'][0])}"
            assert (dep_http, target_set) in edges, f"missing edge {dep_http} -> {target_set}"
        else:
            # Fan-in: all deps converge on a NoOp join that feeds the step.
            join_sources = {src for src, tgt in edges if tgt == target_set}
            assert len(join_sources) == 1
            join_node = join_sources.pop()
            assert _node_by_name(workflow, join_node)["type"] == "n8n-nodes-base.noOp"
            for dep_id in subtask["depends_on"]:
                dep_sub = next(s for s in MARKET_SUBTASKS if s["id"] == dep_id)
                dep_http = f"Run Step [{dep_sub['agent']}]: {dep_sub['title']}"
                assert (dep_http, join_node) in edges, f"missing fan-in edge {dep_http} -> {join_node}"

    # Fan-out: planner step feeds both researcher and analyst contexts.
    planner_http = f"Run Step [planner]: {MARKET_SUBTASKS[0]['title']}"
    planner_targets = {tgt for src, tgt in edges if src == planner_http}
    assert f"Context [researcher]: {MARKET_SUBTASKS[1]['title']}" in planner_targets
    assert f"Context [analyst]: {MARKET_SUBTASKS[2]['title']}" in planner_targets

    # Critic verdict branch wiring.
    critic_http = f"Run Step [critic]: {MARKET_SUBTASKS[4]['title']}"
    assert ("Critic Verdict", "Assemble Report", 0) in _edge_triples(workflow)
    assert ("Critic Verdict", "Flagged for Rework", 1) in _edge_triples(workflow)
    assert (critic_http, "Critic Verdict") in edges
    assert ("Assemble Report", "Deliver Report") in edges


def test_step_context_passes_subtask_identity() -> None:
    """Step HTTP nodes carry the subtask context through body + headers."""
    workflow = export_n8n(_market_snapshot())
    step_http = [n for n in _nodes_of_type(workflow, "n8n-nodes-base.httpRequest") if n["name"] != "Deliver Report"]
    assert len(step_http) == len(MARKET_SUBTASKS)

    for node in step_http:
        params = node["parameters"]
        assert params["method"] == "POST"
        assert "/api/runs/" in params["url"] and "/steps/" in params["url"]
        assert params["jsonBody"] == "={{ $json }}"
        header_names = {h["name"] for h in params["headerParameters"]["parameters"]}
        assert "X-AgentForge-Subtask" in header_names

    # The context Set node upstream holds the static plan fields.
    context_node = _node_by_name(workflow, f"Context [critic]: {MARKET_SUBTASKS[4]['title']}")
    assignment_values = {a["name"]: a["value"] for a in context_node["parameters"]["assignments"]["assignments"]}
    assert assignment_values["subtask_id"] == "st5"
    assert assignment_values["agent"] == "critic"
    assert "st2" in assignment_values["depends_on"] and "st4" in assignment_values["depends_on"]
    assert assignment_values["run_id"].startswith("={{ $('Mission Context')")


# ── 2. Fallback linear pipeline ──────────────────────────────────────────────


def test_fallback_linear_pipeline_when_events_empty() -> None:
    snapshot = _market_snapshot()
    snapshot["events"] = []
    workflow = export_n8n(snapshot)

    assert workflow["meta"]["plan_source"] == "fallback_linear"
    assert workflow["meta"]["subtask_count"] == 3

    # Linear spine: planner -> analyst -> critic -> report, laid out left to right.
    spine = [
        "Webhook Trigger",
        "Mission Context",
        "Context [planner]: Plan the mission",
        "Run Step [planner]: Plan the mission",
        "Context [analyst]: Analyze the data",
        "Run Step [analyst]: Analyze the data",
        "Context [critic]: Critique the findings",
        "Run Step [critic]: Critique the findings",
        "Critic Verdict",
        "Assemble Report",
        "Deliver Report",
    ]
    xs = []
    for name in spine:
        node = _node_by_name(workflow, name)
        assert node is not None, f"fallback pipeline missing node '{name}'"
        xs.append(node["position"][0])
    assert xs == sorted(xs) and len(set(xs)) == len(xs), "spine must run strictly left to right"

    edges = {(src, tgt) for src, tgt, _ in _edge_triples(workflow)}
    assert ("Run Step [planner]: Plan the mission", "Context [analyst]: Analyze the data") in edges
    assert ("Run Step [analyst]: Analyze the data", "Context [critic]: Critique the findings") in edges


def test_no_critic_plan_skips_if_branch() -> None:
    """A plan without a critic subtask still assembles a report via a join."""
    snapshot = _market_snapshot()
    plan = [
        {"id": "st1", "title": "Frame the plan", "agent": "planner", "depends_on": []},
        {"id": "st2", "title": "Collect context", "agent": "researcher", "depends_on": ["st1"]},
        {"id": "st3", "title": "Profile the data", "agent": "analyst", "depends_on": ["st1"]},
    ]
    snapshot["events"] = [_event("plan_created", 2, "planner", {"subtasks": plan})]
    workflow = export_n8n(snapshot)

    assert _nodes_of_type(workflow, "n8n-nodes-base.if") == []
    join = _node_by_name(workflow, "Join: Report Inputs")
    assert join is not None and join["type"] == "n8n-nodes-base.noOp"
    edges = {(src, tgt) for src, tgt, _ in _edge_triples(workflow)}
    assert ("Run Step [researcher]: Collect context", "Join: Report Inputs") in edges
    assert ("Run Step [analyst]: Profile the data", "Join: Report Inputs") in edges
    assert ("Join: Report Inputs", "Assemble Report") in edges
    assert ("Assemble Report", "Deliver Report") in edges


# ── 3. Determinism ───────────────────────────────────────────────────────────


def test_deterministic_output_for_same_input() -> None:
    snapshot = _market_snapshot()
    first = export_n8n(copy.deepcopy(snapshot))
    second = export_n8n(copy.deepcopy(snapshot))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    # Repeated runs of the fallback path are deterministic too.
    empty = copy.deepcopy(snapshot)
    empty["events"] = []
    assert json.dumps(export_n8n(empty), sort_keys=True) == json.dumps(export_n8n(empty), sort_keys=True)


def test_different_runs_produce_distinct_workflows() -> None:
    snapshot_a = _market_snapshot()
    snapshot_b = _market_snapshot()
    snapshot_b["run"] = dict(snapshot_b["run"], id="run-9999-other")
    workflow_a = export_n8n(snapshot_a)
    workflow_b = export_n8n(snapshot_b)
    assert workflow_a != workflow_b
    assert workflow_a["nodes"][0]["parameters"]["path"] == f"agentforge-run-{RUN_ID}"
    assert workflow_b["nodes"][0]["parameters"]["path"] == "agentforge-run-run-9999-other"


# ── 4. URL honesty: AgentForge backend only, env-substituted ────────────────


def test_all_http_urls_target_agentforge_backend_only() -> None:
    workflow = export_n8n(_market_snapshot())
    for node in _nodes_of_type(workflow, "n8n-nodes-base.httpRequest"):
        url = node["parameters"]["url"]
        # Every URL is an n8n expression fed by the env-substituted base URL
        # (Mission Context's api_url) — never a hardcoded third-party host.
        assert url.startswith("="), "URLs must be n8n expressions (env-substituted)"
        assert "api_url" in url
        assert "/api/runs/" in url
        for banned in ("zapier", "make.com", "api.openai.com", "anthropic.com", "hooks.slack.com"):
            assert banned not in url

    # The documented env fallback is the only literal host in expressions.
    assert DEFAULT_API_URL in API_URL_EXPRESSION
    assert API_URL_EXPRESSION.startswith("={{ $env.AGENTFORGE_API_URL")


def test_no_secrets_in_export() -> None:
    workflow = export_n8n(_market_snapshot())
    dumped = json.dumps(workflow)
    assert "sk-" not in dumped
    assert "Bearer " not in dumped
    assert "API_KEY=" not in dumped


# ── 5. Clean degradation on malformed snapshots ──────────────────────────────


def test_non_dict_snapshot_raises_clean_error() -> None:
    for bad in ("not a dict", None, 42, ["list"]):
        with pytest.raises(N8nExportError) as excinfo:
            export_n8n(bad)
        assert "GET /api/runs/{id}" in str(excinfo.value)


def test_garbage_events_fall_back_linear() -> None:
    snapshot = _market_snapshot()
    snapshot["events"] = None
    workflow = export_n8n(snapshot)
    assert workflow["meta"]["plan_source"] == "fallback_linear"

    snapshot["events"] = ["not-a-dict", 42, {"type": "plan_created", "payload": None}]
    workflow = export_n8n(snapshot)
    assert workflow["meta"]["plan_source"] == "fallback_linear"
    assert "no plan_created" in workflow["meta"]["plan_note"] or "no usable" in workflow["meta"]["plan_note"]


def test_plan_with_invalid_subtasks_falls_back() -> None:
    snapshot = _market_snapshot()
    snapshot["events"] = [
        _event("plan_created", 2, "planner", {"subtasks": [{"nope": True}, {"id": "  "}, {"id": 7}]})
    ]
    workflow = export_n8n(snapshot)
    assert workflow["meta"]["plan_source"] == "fallback_linear"


def test_plan_with_dangling_deps_still_exports() -> None:
    """Unknown depends_on ids are dropped (never crash, never fabricate nodes)."""
    snapshot = _market_snapshot()
    plan = [
        {"id": "st1", "title": "Frame the plan", "agent": "planner", "depends_on": []},
        {"id": "st2", "title": "Analyze the data", "agent": "analyst", "depends_on": ["st1", "ghost-step"]},
    ]
    snapshot["events"] = [_event("plan_created", 2, "planner", {"subtasks": plan})]
    workflow = export_n8n(snapshot)

    assert workflow["meta"]["plan_source"] == "plan_created"
    assert workflow["meta"]["subtask_count"] == 2
    names = {node["name"] for node in workflow["nodes"]}
    edges = {(src, tgt) for src, tgt, _ in _edge_triples(workflow)}
    assert ("Run Step [planner]: Frame the plan", "Context [analyst]: Analyze the data") in edges
    for _src, target, _branch in _edge_triples(workflow):
        assert target in names


def test_cyclic_plan_falls_back_linear() -> None:
    snapshot = _market_snapshot()
    plan = [
        {"id": "a", "title": "Step A", "agent": "analyst", "depends_on": ["b"]},
        {"id": "b", "title": "Step B", "agent": "researcher", "depends_on": ["a"]},
    ]
    snapshot["events"] = [_event("plan_created", 2, "planner", {"subtasks": plan})]
    workflow = export_n8n(snapshot)
    assert workflow["meta"]["plan_source"] == "fallback_linear"
    assert "cycle" in workflow["meta"]["plan_note"]


def test_later_plan_event_wins_by_seq() -> None:
    """Re-plans (higher seq) override earlier plans deterministically."""
    snapshot = _market_snapshot()
    snapshot["events"] = [
        _event("plan_created", 2, "planner", {"subtasks": [{"id": "old1", "title": "Old plan step", "agent": "analyst", "depends_on": []}]}),
        _event("plan_created", 9, "planner", {"subtasks": [{"id": "new1", "title": "New plan step", "agent": "forecaster", "depends_on": []}]}),
    ]
    workflow = export_n8n(snapshot)
    assert workflow["meta"]["subtask_count"] == 1
    assert _node_by_name(workflow, "Run Step [forecaster]: New plan step") is not None
    assert _node_by_name(workflow, "Run Step [analyst]: Old plan step") is None


def test_missing_fields_degrade_without_crash() -> None:
    workflow = export_n8n({"run": {}, "mission": {}, "events": []})
    assert workflow["meta"]["agentforge_run_id"] == "unknown-run"
    assert workflow["nodes"][0]["parameters"]["path"] == "agentforge-run-unknown-run"
    assert workflow["meta"]["plan_source"] == "fallback_linear"

    # Hostile run id is sanitized for the webhook path.
    workflow = export_n8n({"run": {"id": "run with spaces/and?slashes"}, "mission": {"goal": "Goal here"}, "events": []})
    assert workflow["nodes"][0]["parameters"]["path"] == "agentforge-run-run-with-spaces-and-slashes"

    # A goal with quotes/newlines survives the JS-escape baked into expressions.
    workflow = export_n8n({"run": {"id": "r1"}, "mission": {"goal": "It's a \"goal\"\nwith lines"}, "events": []})
    context = _node_by_name(workflow, "Mission Context")
    goal_assignment = next(a for a in context["parameters"]["assignments"]["assignments"] if a["name"] == "goal")
    assert "It\\'s a \"goal\"\\nwith lines" in goal_assignment["value"]
    assert json.loads(json.dumps(workflow)) == workflow
