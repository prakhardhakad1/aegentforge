"""Tests for template DAGs: acyclicity utility, references, roles, composition."""

from __future__ import annotations

import pytest

from orchestrator.templates import (
    MARKET_RESEARCH_TEAM,
    SALES_INSIGHTS_TEAM,
    SUPPORT_TRIAGE_TEAM,
    PINNED_ROLES,
    TEMPLATES,
    dag_problems,
    get_template,
    is_dag_acyclic,
)


def _node(node_id: str, agent: str, depends_on: list[str]) -> dict[str, object]:
    return {"id": node_id, "title": node_id.upper(), "agent": agent, "depends_on": depends_on}


# ---------------------------------------------------------------------------
# is_dag_acyclic utility
# ---------------------------------------------------------------------------


def test_util_accepts_a_simple_chain() -> None:
    chain = [
        _node("a", "analyst", []),
        _node("b", "forecaster", ["a"]),
        _node("c", "critic", ["b"]),
    ]
    assert is_dag_acyclic(chain) is True


def test_util_accepts_a_diamond() -> None:
    diamond = [
        _node("a", "analyst", []),
        _node("b", "researcher", ["a"]),
        _node("c", "researcher", ["a"]),
        _node("d", "critic", ["b", "c"]),
    ]
    assert is_dag_acyclic(diamond) is True


def test_util_rejects_a_three_node_cycle() -> None:
    cycle = [
        _node("a", "critic", ["c"]),
        _node("b", "critic", ["a"]),
        _node("c", "critic", ["b"]),
    ]
    assert is_dag_acyclic(cycle) is False


def test_util_rejects_a_self_loop() -> None:
    assert is_dag_acyclic([_node("a", "critic", ["a"])]) is False


def test_util_rejects_duplicate_node_ids() -> None:
    duplicated = [
        _node("a", "analyst", []),
        _node("a", "critic", ["a"]),
    ]
    assert is_dag_acyclic(duplicated) is False


def test_util_treats_unknown_dependencies_as_external_inputs() -> None:
    # A dependency on a node outside this list cannot create a cycle here;
    # dag_problems is the place that flags it.
    assert is_dag_acyclic([_node("a", "critic", ["ghost"])]) is True


def test_util_handles_empty_list() -> None:
    assert is_dag_acyclic([]) is True


def test_dag_problems_reports_unknown_dependency_and_cycle() -> None:
    problems = dag_problems(
        [
            _node("a", "critic", ["ghost"]),
            _node("b", "critic", ["c"]),
            _node("c", "critic", ["b"]),
        ]
    )
    assert any("ghost" in problem for problem in problems)
    assert any("cycle" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Every template's expected_dag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template_id",
    ["market_research_team", "sales_insights_team", "support_triage_team"],
)
def test_template_dag_is_acyclic_with_valid_references(template_id: str) -> None:
    dag = get_template(template_id)["expected_dag"]
    assert is_dag_acyclic(dag) is True
    assert dag_problems(dag) == []
    node_ids = {node["id"] for node in dag}
    for node in dag:
        assert set(node["depends_on"]) <= node_ids
        for dep in node["depends_on"]:
            dep_node = next(n for n in dag if n["id"] == dep)
            assert dag.index(dep_node) < dag.index(node)  # listed in topological order


def test_every_dag_agent_is_a_pinned_role_and_on_the_team() -> None:
    for template in TEMPLATES:
        team_roles = {member["role"] for member in template["team"]}
        for node in template["expected_dag"]:
            assert node["agent"] in PINNED_ROLES
            assert node["agent"] in team_roles


def test_every_dag_node_id_is_unique() -> None:
    for template in TEMPLATES:
        node_ids = [node["id"] for node in template["expected_dag"]]
        assert len(node_ids) == len(set(node_ids))


# ---------------------------------------------------------------------------
# Team composition and expected flow per brief
# ---------------------------------------------------------------------------


def test_market_research_team_composition_and_parallel_research() -> None:
    template = MARKET_RESEARCH_TEAM
    roles = [member["role"] for member in template["team"]]
    assert roles.count("researcher") == 2
    assert roles.count("analyst") == 1
    assert roles.count("critic") == 1
    roots = [node for node in template["expected_dag"] if not node["depends_on"]]
    assert len(roots) == 2
    assert all(node["agent"] == "researcher" for node in roots)
    critic_node = next(
        node for node in template["expected_dag"] if node["agent"] == "critic"
    )
    # The critic reviews the gap analysis AND the drafted recommendations.
    assert sorted(critic_node["depends_on"]) == ["t3", "t4"]


def test_sales_insights_team_composition_and_flow() -> None:
    template = SALES_INSIGHTS_TEAM
    roles = [member["role"] for member in template["team"]]
    assert sorted(roles) == ["analyst", "critic", "forecaster"]
    dag = template["expected_dag"]
    analyst_node = next(node for node in dag if node["id"] == "t1")
    forecaster_node = next(node for node in dag if node["id"] == "t2")
    recommendations_node = next(node for node in dag if node["id"] == "t3")
    critic_node = next(node for node in dag if node["agent"] == "critic")
    assert analyst_node["depends_on"] == []
    assert forecaster_node["depends_on"] == ["t1"]  # forecast needs verified stats
    assert sorted(recommendations_node["depends_on"]) == ["t1", "t2"]
    assert sorted(critic_node["depends_on"]) == ["t1", "t2", "t3"]


def test_support_triage_team_composition_and_flow() -> None:
    template = SUPPORT_TRIAGE_TEAM
    roles = [member["role"] for member in template["team"]]
    assert sorted(roles) == ["analyst", "critic", "researcher"]
    dag = template["expected_dag"]
    analyst_node = next(node for node in dag if node["id"] == "t1")
    researcher_node = next(node for node in dag if node["id"] == "t2")
    staffing_node = next(node for node in dag if node["id"] == "t3")
    critic_node = next(node for node in dag if node["agent"] == "critic")
    assert analyst_node["depends_on"] == []
    assert researcher_node["depends_on"] == []  # runs in parallel with the analyst
    assert sorted(staffing_node["depends_on"]) == ["t1", "t2"]
    assert sorted(critic_node["depends_on"]) == ["t1", "t2", "t3"]


def test_every_team_has_exactly_one_critic() -> None:
    for template in TEMPLATES:
        critics = [member for member in template["team"] if member["role"] == "critic"]
        assert len(critics) == 1


def test_critic_is_the_final_stage_of_every_dag() -> None:
    # Engine contract (orchestrator.planner.Plan.validate): nothing may run
    # after the critic except the engine's own revision slot, which templates
    # cannot express — so no DAG node may depend on the critic and the critic
    # must be listed last.
    for template in TEMPLATES:
        dag = template["expected_dag"]
        critic_nodes = [node for node in dag if node["agent"] == "critic"]
        assert len(critic_nodes) == 1, f"{template['id']}: need exactly one critic node"
        critic_id = critic_nodes[0]["id"]
        assert dag[-1]["id"] == critic_id, f"{template['id']}: critic must be last"
        for node in dag:
            assert critic_id not in node["depends_on"], (
                f"{template['id']}: node {node['id']} depends on the critic"
            )


# ---------------------------------------------------------------------------
# Integration with the orchestrator engine's planner (Agent 3)
# ---------------------------------------------------------------------------


def test_engine_planner_accepts_every_template_dag() -> None:
    """The engine's template_plan must accept our DAGs verbatim.

    This is the load-bearing integration check: it runs the exact code path a
    live run takes (build subtasks from ``expected_dag``, append the critic
    revision slot, normalize, validate). If the engine ever rejects a template
    here, the planner silently falls back to heuristics and the marketplace
    template never drives a run.
    """
    planner = pytest.importorskip("orchestrator.planner")
    for template in TEMPLATES:
        plan = planner.template_plan(template["id"], template["sample_mission"])
        assert plan is not None, f"engine rejected template {template['id']!r}"
        assert plan.strategy == "template"
        agent_sequence = [subtask.agent for subtask in plan.subtasks]
        assert agent_sequence[-2] == "critic"  # revision slot is last
        assert plan.subtasks[-1].is_revision_slot
