"""Regression tests for scoring defects inherited from gnw-evals.

This harness was ported from gnw-evals (github.com/wri/gnw-evals), and these
defects came with it:

- AOI check: a case that expects places but resolves none scores 0.0, not
  None (`test_f1_*`).
- Dashboard widgets: text widgets are read from `config.text` (the legacy
  flat `text` key still works), and an empty dashboard fails validity only
  when the case expected widgets (`test_f3_*`).
- Judge outages: a failed LLM judge call scores None and is listed in
  `judge_errors`; it never becomes a pass or a fail (`test_f4_*`).
- Chart serialisation: charts sent to the judge stay valid JSON when
  truncated for size (`test_f5_*`).
- Judge schemas: the reasoning field comes before the score, because the
  judge model commits to the first field it emits (`test_f6_*`).

The remaining defect (a chart expected but none produced) is tested in
test_guards.py as `test_f2_*`.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from goldset.evaluators import answer_evaluator, clarification_evaluator
from goldset.evaluators.answer_evaluator import (
    _serialize_charts_json,
    evaluate_final_answer,
)
from goldset.evaluators.aoi_evaluator import evaluate_aoi_selection
from goldset.evaluators.clarification_evaluator import evaluate_clarification
from goldset.evaluators.dashboard_evaluator import evaluate_dashboard_widgets
from goldset.evaluators.llm_judges import JudgeError

JUDGES_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "goldset"
    / "evaluators"
    / "llm_judges.py"
).read_text()


# --- expected AOIs but none resolved -> 0.0, not silence


def test_f1_missing_aoi_fails_when_expected():
    result = evaluate_aoi_selection({}, ["BRA.25_1"], "query")
    assert result["aoi_id_match_score"] == 0.0


def test_f1_no_expectation_still_skips():
    assert evaluate_aoi_selection({}, [], "query")["aoi_id_match_score"] is None


# --- widget text key and empty dashboards


def test_f3_text_widget_reads_config_text():
    dashboard = {"widgets": [{"widget_type": "text", "config": {"text": "# hi"}}]}
    result = evaluate_dashboard_widgets(dashboard, ["text"])
    assert result["dashboard_widgets_valid_score"] == 1.0
    assert result["dashboard_widgets_match_score"] == 1.0


def test_f3_legacy_flat_text_key_still_accepted():
    dashboard = {"widgets": [{"widget_type": "text", "text": "# hi"}]}
    assert (
        evaluate_dashboard_widgets(dashboard, ["text"])["dashboard_widgets_valid_score"]
        == 1.0
    )


# --- the live alerts widget (PZB-1468) persists an area and a layer snapshot


def _alerts_widget(**config):
    return {"widget_type": "alerts", "config": config}


def test_alerts_widget_valid_with_area_and_layer():
    dashboard = {
        "widgets": [
            _alerts_widget(
                alerts={
                    "aoi": {
                        "source": "gadm",
                        "src_id": "BRA.16_1",
                        "subtype": "state-province",
                        "name": "Paraná",
                    },
                    "days": 30,
                },
                dataset={"dataset_id": 11, "tile_url": "https://tiles/{z}/{x}/{y}.png"},
            )
        ]
    }
    result = evaluate_dashboard_widgets(dashboard, ["alerts"])
    assert result["dashboard_widgets_valid_score"] == 1.0
    assert result["dashboard_widgets_match_score"] == 1.0


def test_alerts_widget_invalid_without_area_or_layer():
    no_area = {
        "widgets": [
            _alerts_widget(dataset={"tile_url": "https://tiles/{z}/{x}/{y}.png"})
        ]
    }
    no_layer = {
        "widgets": [_alerts_widget(alerts={"aoi": {"src_id": "BRA.16_1"}}, dataset={})]
    }
    for dashboard in (no_area, no_layer):
        assert (
            evaluate_dashboard_widgets(dashboard, ["alerts"])[
                "dashboard_widgets_valid_score"
            ]
            == 0.0
        )


def test_f3_empty_dashboard_fails_validity_when_widgets_were_expected():
    """An empty dashboard fails validity only when the case expected widgets.

    1-096 ("Create a dashboard for brazil") expects no widgets and cannot
    express one. Failing its empty dashboard would punish the agent for
    obeying the prompt and reward it for adding a widget nobody asked for,
    which `evaluate_dashboard_created` counts as a violation.
    """
    assert (
        evaluate_dashboard_widgets({"widgets": []}, ["map"])[
            "dashboard_widgets_valid_score"
        ]
        == 0.0
    )
    # nothing requested -> nothing to validate
    assert (
        evaluate_dashboard_widgets({"widgets": []}, None)[
            "dashboard_widgets_valid_score"
        ]
        is None
    )
    # no dashboard at all is still "nothing to check"
    assert (
        evaluate_dashboard_widgets(None, None)["dashboard_widgets_valid_score"] is None
    )


# --- judge outage -> None plus judge_errors, never a verdict

STATE = {
    "messages": [SimpleNamespace(content="The answer is 42 hectares.")],
    "charts_data": [{"type": "bar", "data": [{"y": 2020, "area_ha": 42.0}]}],
    "codeact_parts": [],
}


def _boom(*args, **kwargs):
    raise RuntimeError("anthropic 529: overloaded")


def test_f4_answer_judges_error_loudly(monkeypatch):
    monkeypatch.setattr(answer_evaluator, "llm_judge", _boom)
    monkeypatch.setattr(answer_evaluator, "llm_judge_chart", _boom)
    monkeypatch.setattr(answer_evaluator, "llm_judge_expected_text", _boom)
    result = evaluate_final_answer(STATE, "42 hectares", "mentions hectares", "q")
    assert result["agent_answer_score"] is None
    assert result["charts_answer_score"] is None
    assert result["expected_text_match_score"] is None
    assert sorted(result["judge_errors"]) == [
        "agent_answer",
        "charts_answer",
        "expected_text_match",
    ]
    assert "JUDGE ERROR" in result["agent_answer_score_reason"]


def test_f4_clarification_outage_no_longer_scores(monkeypatch):
    def raising(*args, **kwargs):
        raise JudgeError("clarification_requested", RuntimeError("outage"))

    monkeypatch.setattr(clarification_evaluator, "llm_judge_clarification", raising)
    # expected=False + outage used to score 1.0 (swallowed to actual=False)
    result = evaluate_clarification(STATE, False, "query")
    assert result["clarification_requested_score"] is None
    assert result["judge_errors"] == ["clarification_requested"]


# --- chart serialisation is valid JSON at every size


def test_f5_small_charts_unchanged():
    charts = [{"type": "bar", "data": [{"a": 1}], "insight": "dropped"}]
    parsed = json.loads(_serialize_charts_json(charts))
    assert parsed == [{"type": "bar", "data": [{"a": 1}]}]


def test_f5_oversized_charts_stay_parseable_and_marked():
    big_rows = [{"name": f"row-{i}", "value": i * 1.234567} for i in range(3000)]
    charts = [{"id": f"c{i}", "type": "bar", "data": list(big_rows)} for i in range(4)]
    serialized = _serialize_charts_json(charts)
    assert len(serialized) <= 80_000
    parsed = json.loads(serialized)  # the old blind slice raised here
    assert parsed[0]["_truncated"] is True
    assert parsed[0]["data"]  # numeric content survives for chart_numeric


# --- reasoning precedes the verdict in every judge schema


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("explanation: str", "is_clarification: bool"),
        ("reason: str", "score: int"),
    ],
)
def test_f6_reasoning_fields_precede_scores(first, second):
    assert JUDGES_SOURCE.index(first) < JUDGES_SOURCE.index(second)


def test_f6_no_score_first_models_remain():
    for model_block in JUDGES_SOURCE.split("class ")[1:]:
        body = model_block.split("def ")[0]
        if "score: int" in body and "reason: str" in body:
            assert body.index("reason: str") < body.index("score: int"), model_block[
                :60
            ]
