"""GET /api/templates — pinned ids and Template shape."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas.common import AGENT_ROLES

PINNED_TEMPLATE_IDS = {
    "market_research_team",
    "sales_insights_team",
    "support_triage_team",
}


def test_templates_lists_all_pinned_ids(client: TestClient) -> None:
    response = client.get("/api/templates")
    assert response.status_code == 200
    templates = response.json()["templates"]
    ids = {t["id"] for t in templates}
    assert PINNED_TEMPLATE_IDS <= ids


def test_template_shape_complete(client: TestClient) -> None:
    templates = client.get("/api/templates").json()["templates"]
    by_id = {t["id"]: t for t in templates}
    for template_id in PINNED_TEMPLATE_IDS:
        template = by_id[template_id]
        assert template["name"]
        assert template["description"]
        assert isinstance(template["tags"], list) and template["tags"]
        assert template["planner_prompt"].strip(), "planner prompt must be non-empty"
        assert template["sample_mission"].strip()
        assert isinstance(template["report_outline"], list) and template["report_outline"]

        # team: every member has role/title/system_prompt with pinned roles
        roles = [member["role"] for member in template["team"]]
        assert set(roles) <= set(AGENT_ROLES)
        for member in template["team"]:
            assert member["title"].strip()
            assert len(member["system_prompt"].strip()) > 40

        # expected DAG: unique ids, known agents, deps reference existing ids
        dag = template["expected_dag"]
        node_ids = {node["id"] for node in dag}
        assert len(node_ids) == len(dag) and node_ids
        for node in dag:
            assert node["agent"] in AGENT_ROLES
            assert node["title"].strip()
            assert set(node["depends_on"]) <= node_ids
        # at least one node depends on others (real DAG, not a flat list)
        assert any(node["depends_on"] for node in dag)


def test_templates_served_from_db_seed(client: TestClient) -> None:
    """The rows must come from the seeded Template table (not just code)."""
    from app.db.base import session_scope
    from app.models import Template

    with session_scope() as db:
        rows = db.query(Template).all()
    assert {row.id for row in rows} >= PINNED_TEMPLATE_IDS
