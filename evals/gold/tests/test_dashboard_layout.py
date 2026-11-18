"""dashboard_sections_match and dashboard_text_match."""

from goldset.eval_types import ExpectedData
from goldset.evaluators.dashboard_evaluator import evaluate_dashboard_layout

DASHBOARD = {
    "sections": [{"id": "s1", "title": "Methods"}, {"id": "s2", "title": "Trends"}],
    "widgets": [
        {
            "widget_type": "text",
            "section_id": "s1",
            "config": {"text": "Uses a 25% threshold."},
        },
        {"widget_type": "insight", "section_id": "s2"},
        {"widget_type": "map", "section_id": None, "config": {}},
    ],
}


def _run(sections=None, text=None, dashboard=DASHBOARD):
    return evaluate_dashboard_layout(dashboard, sections, text)


def test_sections_match_title_and_types():
    assert (
        _run({"methods": ["text"], "Trends": ["insight"]})[
            "dashboard_sections_match_score"
        ]
        == 1.0
    )


def test_section_with_no_types_only_needs_to_exist():
    assert _run({"Methods": []})["dashboard_sections_match_score"] == 1.0


def test_missing_section_or_wrong_widget_fails():
    assert _run({"Background": []})["dashboard_sections_match_score"] == 0.0
    assert _run({"Methods": ["map"]})["dashboard_sections_match_score"] == 0.0


def test_text_phrases():
    assert _run(text=["25%"])["dashboard_text_match_score"] == 1.0
    assert _run(text=["25%", "30%"])["dashboard_text_match_score"] == 0.0


def test_abstains_without_expectation_or_dashboard():
    result = _run()
    assert result["dashboard_sections_match_score"] is None
    assert result["dashboard_text_match_score"] is None
    assert (
        _run({"Methods": []}, ["25%"], dashboard=None)["dashboard_sections_match_score"]
        is None
    )


def test_expected_fields_parse_from_case_strings():
    expected = ExpectedData(
        expected_dashboard_sections="Methods: text; Trends: insight, map; Empty",
        expected_dashboard_text="25%; threshold",
    )
    assert expected.expected_dashboard_sections == {
        "Methods": ["text"],
        "Trends": ["insight", "map"],
        "Empty": [],
    }
    assert expected.expected_dashboard_text == ["25%", "threshold"]
