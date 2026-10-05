"""Tests for prompt quality: non-trivial length, tool specificity, contracts."""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.templates import TEMPLATES, get_template

MIN_SYSTEM_PROMPT_CHARS: int = 200
MIN_PLANNER_PROMPT_CHARS: int = 200
MIN_SAMPLE_MISSION_CHARS: int = 60
MIN_DESCRIPTION_CHARS: int = 80
MIN_OUTLINE_SECTIONS: int = 4


def _members(template: dict[str, Any], role: str) -> list[dict[str, Any]]:
    return [member for member in template["team"] if member["role"] == role]


# ---------------------------------------------------------------------------
# Non-trivial content
# ---------------------------------------------------------------------------


def test_every_system_prompt_is_nontrivial() -> None:
    for template in TEMPLATES:
        for member in template["team"]:
            prompt = member["system_prompt"]
            assert len(prompt) > MIN_SYSTEM_PROMPT_CHARS, (
                f"{template['id']}/{member['title']}: system_prompt too short "
                f"({len(prompt)} chars)"
            )


def test_every_planner_prompt_is_nontrivial() -> None:
    for template in TEMPLATES:
        prompt = template["planner_prompt"]
        assert len(prompt) > MIN_PLANNER_PROMPT_CHARS, (
            f"{template['id']}: planner_prompt too short ({len(prompt)} chars)"
        )


def test_every_sample_mission_is_vivid() -> None:
    for template in TEMPLATES:
        mission = template["sample_mission"]
        assert len(mission) >= MIN_SAMPLE_MISSION_CHARS
        assert mission.strip() and mission.strip() == mission


def test_every_description_names_when_to_hire_the_team() -> None:
    for template in TEMPLATES:
        assert len(template["description"]) >= MIN_DESCRIPTION_CHARS


def test_every_template_has_tags_and_a_substantial_outline() -> None:
    for template in TEMPLATES:
        assert template["tags"], f"{template['id']} has no tags"
        assert all(isinstance(tag, str) and tag for tag in template["tags"])
        outline = template["report_outline"]
        assert len(outline) >= MIN_OUTLINE_SECTIONS
        assert all(isinstance(section, str) and section.strip() for section in outline)


def test_team_titles_are_distinct_within_a_team() -> None:
    for template in TEMPLATES:
        titles = [member["title"] for member in template["team"]]
        assert len(titles) == len(set(titles))


# ---------------------------------------------------------------------------
# Role-specific tool and contract specificity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template_id", ["market_research_team", "support_triage_team"]
)
def test_researcher_prompts_specify_web_search_and_citations(
    template_id: str,
) -> None:
    for member in _members(get_template(template_id), "researcher"):
        prompt = member["system_prompt"]
        assert "web_search" in prompt, f"{template_id}/{member['title']} lacks tool"
        assert "source_urls" in prompt, f"{template_id}/{member['title']} lacks citations"
        assert "never" in prompt.lower()  # explicit hard bans


@pytest.mark.parametrize(
    "template_id", ["market_research_team", "sales_insights_team", "support_triage_team"]
)
def test_analyst_prompts_specify_csv_analyzer_code_sandbox_and_chartspecs(
    template_id: str,
) -> None:
    for member in _members(get_template(template_id), "analyst"):
        prompt = member["system_prompt"]
        assert "csv_analyzer" in prompt, f"{template_id}/{member['title']} lacks tool"
        assert "code_sandbox" in prompt, f"{template_id}/{member['title']} lacks tool"
        assert "chart" in prompt.lower(), f"{template_id}/{member['title']} lacks charts"
        assert "kind" in prompt and "data" in prompt  # ChartSpec fields


def test_forecaster_prompt_requires_confidence_and_basis() -> None:
    for member in _members(get_template("sales_insights_team"), "forecaster"):
        prompt = member["system_prompt"]
        assert "confidence" in prompt
        assert "basis" in prompt
        assert "never predict without a basis" in prompt.lower()


@pytest.mark.parametrize(
    "template_id", ["market_research_team", "sales_insights_team", "support_triage_team"]
)
def test_critic_prompts_reject_unsupported_claims(template_id: str) -> None:
    for member in _members(get_template(template_id), "critic"):
        prompt = member["system_prompt"]
        assert "approved" in prompt  # explicit verdict contract
        assert "unsupported" in prompt.lower()
        assert "never approve" in prompt.lower()


def test_no_prompt_contains_placeholder_text() -> None:
    banned = ("todo", "tbd", "fill in", "lorem ipsum")
    for template in TEMPLATES:
        texts = [template["planner_prompt"], template["sample_mission"]]
        texts += [member["system_prompt"] for member in template["team"]]
        for text in texts:
            lowered = text.lower()
            for marker in banned:
                assert marker not in lowered, f"{template['id']} contains {marker!r}"


def test_planner_prompts_reference_their_own_dag_ids_and_titles() -> None:
    for template in TEMPLATES:
        planner_prompt = template["planner_prompt"]
        for node in template["expected_dag"]:
            assert node["id"] in planner_prompt, (
                f"{template['id']}: planner_prompt omits DAG id {node['id']}"
            )
            assert node["title"] in planner_prompt, (
                f"{template['id']}: planner_prompt omits DAG title {node['title']!r}"
            )
