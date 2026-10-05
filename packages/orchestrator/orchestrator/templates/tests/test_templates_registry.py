"""Tests for the template registry: pinned ids, lookups, API shape, validation."""

from __future__ import annotations

import copy

import pytest

from orchestrator.templates import (
    MARKET_RESEARCH_TEAM,
    SALES_INSIGHTS_TEAM,
    SUPPORT_TRIAGE_TEAM,
    TEMPLATES,
    TEMPLATES_BY_ID,
    TEMPLATE_IDS,
    as_api_shape,
    get_template,
    validate_all,
    validate_template,
)
import orchestrator.templates.registry as registry_module

PINNED_IDS: tuple[str, ...] = (
    "market_research_team",
    "sales_insights_team",
    "support_triage_team",
)
PINNED_TEMPLATE_KEYS: set[str] = {
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
PINNED_TEAM_KEYS: set[str] = {"role", "title", "system_prompt"}
PINNED_DAG_KEYS: set[str] = {"id", "title", "agent", "depends_on"}


# ---------------------------------------------------------------------------
# Registry contents
# ---------------------------------------------------------------------------


def test_validate_all_passes_and_returns_pinned_ids() -> None:
    assert validate_all() == list(PINNED_IDS)


def test_exactly_three_templates_with_pinned_ids() -> None:
    assert len(TEMPLATES) == 3
    assert TEMPLATE_IDS == PINNED_IDS
    assert [template["id"] for template in TEMPLATES] == list(PINNED_IDS)
    assert set(TEMPLATES_BY_ID) == set(PINNED_IDS)


def test_team_modules_export_their_templates() -> None:
    assert MARKET_RESEARCH_TEAM["id"] == "market_research_team"
    assert SALES_INSIGHTS_TEAM["id"] == "sales_insights_team"
    assert SUPPORT_TRIAGE_TEAM["id"] == "support_triage_team"


def test_every_template_matches_pinned_shape_exactly() -> None:
    for template in TEMPLATES:
        assert set(template.keys()) == PINNED_TEMPLATE_KEYS
        for member in template["team"]:
            assert set(member.keys()) == PINNED_TEAM_KEYS
        for node in template["expected_dag"]:
            assert set(node.keys()) == PINNED_DAG_KEYS


# ---------------------------------------------------------------------------
# get_template
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_id", list(PINNED_IDS))
def test_get_template_returns_registered_template(template_id: str) -> None:
    template = get_template(template_id)
    assert template["id"] == template_id
    assert template is TEMPLATES_BY_ID[template_id]


def test_get_template_error_message_names_unknown_and_available_ids() -> None:
    with pytest.raises(KeyError) as excinfo:
        get_template("churn_busters_team")
    message = str(excinfo.value)
    assert "churn_busters_team" in message
    for pinned_id in PINNED_IDS:
        assert pinned_id in message


# ---------------------------------------------------------------------------
# as_api_shape
# ---------------------------------------------------------------------------


def test_as_api_shape_has_exactly_pinned_keys() -> None:
    for template in TEMPLATES:
        shape = as_api_shape(template)
        assert set(shape.keys()) == PINNED_TEMPLATE_KEYS
        assert len(shape["team"]) == len(template["team"])
        for member in shape["team"]:
            assert set(member.keys()) == PINNED_TEAM_KEYS
        assert len(shape["expected_dag"]) == len(template["expected_dag"])
        for node in shape["expected_dag"]:
            assert set(node.keys()) == PINNED_DAG_KEYS
        assert isinstance(shape["tags"], list)
        assert isinstance(shape["report_outline"], list)


def test_as_api_shape_is_a_deep_copy() -> None:
    template = TEMPLATES[0]
    snapshot = copy.deepcopy(template)
    shape = as_api_shape(template)
    shape["tags"].append("tampered")
    shape["team"][0]["system_prompt"] = "tampered"
    shape["expected_dag"][0]["depends_on"].append("tampered")
    assert template == snapshot  # registry untouched


def test_as_api_shape_round_trips_json_serializable() -> None:
    import json

    for template in TEMPLATES:
        encoded = json.dumps(as_api_shape(template))  # must not raise
        assert isinstance(encoded, str)


# ---------------------------------------------------------------------------
# validate_all / validate_template rejection paths
# ---------------------------------------------------------------------------


def _mutated_template(**changes: object) -> dict[str, object]:
    template: dict[str, object] = copy.deepcopy(TEMPLATES[0])
    template.update(changes)  # type: ignore[arg-type]
    return template


def test_validate_template_rejects_missing_pinned_key() -> None:
    template = copy.deepcopy(TEMPLATES[0])
    del template["sample_mission"]
    with pytest.raises(ValueError, match="sample_mission"):
        validate_template(template)


def test_validate_template_rejects_extra_key() -> None:
    template = copy.deepcopy(TEMPLATES[0])
    template["bonus_field"] = "not pinned"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="bonus_field"):
        validate_template(template)


def test_validate_template_rejects_invalid_role() -> None:
    template = copy.deepcopy(TEMPLATES[0])
    template["team"][0]["role"] = "intern"
    with pytest.raises(ValueError, match="invalid role"):
        validate_template(template)


def test_validate_template_rejects_team_without_exactly_one_critic() -> None:
    template = copy.deepcopy(TEMPLATES[0])
    template["team"] = [member for member in template["team"] if member["role"] != "critic"]
    with pytest.raises(ValueError, match="exactly one critic"):
        validate_template(template)


def test_validate_template_rejects_two_critics() -> None:
    template = copy.deepcopy(TEMPLATES[0])
    second_critic = copy.deepcopy(template["team"][-1])
    template["team"].append(second_critic)
    with pytest.raises(ValueError, match="exactly one critic"):
        validate_template(template)


def test_validate_template_rejects_empty_sample_mission() -> None:
    with pytest.raises(ValueError, match="sample_mission"):
        validate_template(_mutated_template(sample_mission="   "))


def test_validate_template_rejects_short_prompt() -> None:
    with pytest.raises(ValueError, match="planner_prompt"):
        validate_template(_mutated_template(planner_prompt="too short"))


def test_validate_template_rejects_unknown_dependency() -> None:
    template = copy.deepcopy(TEMPLATES[0])
    template["expected_dag"][2]["depends_on"].append("ghost")
    with pytest.raises(ValueError, match="unknown node"):
        validate_template(template)


def test_validate_all_rejects_duplicate_template_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = copy.deepcopy(TEMPLATES[0])  # same id as TEMPLATES[0]
    monkeypatch.setattr(registry_module, "TEMPLATES", [TEMPLATES[0], duplicate])
    with pytest.raises(ValueError, match="duplicate template id"):
        registry_module.validate_all()
