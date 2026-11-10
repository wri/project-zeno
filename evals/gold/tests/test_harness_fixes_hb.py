"""Tests for four deliberate changes to what a check measures.

- `classify_scope` counts a `dataset_choice` nudge with no data pull as
  `suggest` (`test_h4_*`).
- `charts_answer` is decided by the deterministic numeric comparison: it
  passes or fails on whether the chart data contains the expected figure,
  and abstains when there is no figure to compare. The LLM judge's verdict
  is kept as the info-only check `charts_answer_judge` (`test_h5_*`).
- Chart candidate figures include row sums across measure columns and their
  grand total (`test_h6_*`).
- `dashboard_widgets_valid` abstains on an empty dashboard when the case
  expects no widgets (`test_h7_*`).

A run that spans a change like these should say so with `gold run --note`,
so its diff is not read as the agent getting better or worse. The h numbers
continue from test_harness_fixes_ha.py and are unrelated to the h numbers in
test_hardening.py.
"""

import json

from goldset.buckets import INFO_ONLY, is_info_only
from goldset.evaluators.chart_numeric import (
    chart_candidate_values,
    evaluate_numeric_support,
)
from goldset.evaluators.dashboard_evaluator import evaluate_dashboard_widgets
from goldset.evaluators.llm_judges import resolve_chart_verdict
from goldset.evaluators.scope_checks import classify_scope, evaluate_scope

TOLERANCE = 0.02


# ----------------------------------------- classify_scope: dataset_choice nudge


def test_h4_dataset_choice_nudge_without_a_pull_is_suggest():
    """`suggested_datasets` is populated in 0 of 1,298 retained trials; the
    product moved suggestion onto the nudge surface (project-zeno#770)."""
    state = {
        "statistics": None,
        "suggested_datasets": [],
        "nudge": {"type": "dataset_choice", "options": ["Global land cover"]},
    }
    assert classify_scope(state) == "suggest"
    assert evaluate_scope(state, "suggest")["scope_match_score"] == 1.0


def test_h4_aoi_choice_nudge_is_still_clarify():
    """1-105 and mt-002 disambiguate an AOI: a different class, unaffected."""
    state = {
        "statistics": None,
        "suggested_datasets": [],
        "nudge": {"type": "aoi_choice", "options": ["Puri, Odisha, India"]},
    }
    assert classify_scope(state) == "clarify"


def test_h4_a_pull_still_outranks_any_nudge():
    """Precedence is unchanged: an agent that pulled data has analysed."""
    state = {
        "statistics": {"data": [1]},
        "suggested_datasets": [],
        "nudge": {"type": "dataset_choice"},
    }
    assert classify_scope(state) == "analyse"


def test_h4_populated_suggested_datasets_still_suggests():
    """If the product ever repopulates the field, the old path must still work."""
    state = {"statistics": None, "suggested_datasets": ["4"], "nudge": {}}
    assert classify_scope(state) == "suggest"


# --------------------------------------- charts_answer: numeric support decides


def test_h5_numeric_support_decides_when_it_can():
    """1-059: the chart's data contained the global total to 0.07%, and the judge
    failed it anyway on framing, then passed an identical third trial."""
    verdict = resolve_chart_verdict(
        judge_score=0,
        judge_reason="regional breakdown only",
        support="supported",
        explanation="0.07% difference",
    )
    assert verdict["score"] == 1.0
    assert verdict["judge_score"] == 0.0
    assert "info-only" in verdict["reason"]


def test_h5_unsupported_still_fails_even_when_the_judge_liked_it():
    verdict = resolve_chart_verdict(
        judge_score=1,
        judge_reason="looks fine",
        support="unsupported",
        explanation="212% difference",
    )
    assert verdict["score"] == 0.0
    assert verdict["judge_score"] == 1.0


def test_h5_no_numeric_claim_abstains_rather_than_deferring_to_the_judge():
    """1-001 expects TRUE, 1-004 expects 'Brazil': the comparator has nothing to
    work with, so the row must not carry a gating chart verdict at all."""
    verdict = resolve_chart_verdict(
        judge_score=0, judge_reason="disliked the chart", support=None, explanation=""
    )
    assert verdict["score"] is None
    assert verdict["judge_score"] == 0.0


def test_h5_judge_verdict_is_tagged_info_only():
    assert "charts_answer_judge" in INFO_ONLY
    assert is_info_only("charts_answer_judge")
    assert is_info_only("t2.charts_answer_judge")


# ------------------------------------------ chart candidates: cross-column sums

# 1-002: São Paulo alerts split across two confidence-tier columns. Neither
# column total is the answer; their sum (1,299,278.14) is.
SAO_PAULO_TIERS = json.dumps(
    [
        {
            "type": "bar",
            "data": [
                {
                    "month": "2024-07",
                    "high_confidence_ha": 291_728.59,
                    "highest_confidence_ha": 3_904.92,
                },
                {
                    "month": "2024-08",
                    "high_confidence_ha": 994_598.80,
                    "highest_confidence_ha": 9_045.83,
                },
            ],
        },
    ],
)


def test_h6_cross_column_grand_total_is_a_candidate():
    values = chart_candidate_values(SAO_PAULO_TIERS)
    expected_total = 291_728.59 + 3_904.92 + 994_598.80 + 9_045.83
    assert any(abs(v - expected_total) < 0.01 for v in values), expected_total


def test_h6_cross_column_row_sums_are_candidates():
    values = chart_candidate_values(SAO_PAULO_TIERS)
    july_combined = 291_728.59 + 3_904.92
    assert any(abs(v - july_combined) < 0.01 for v in values)


def test_h6_makes_1_002_supported_at_its_recorded_figure():
    """The agent reports 1,299,278.14 on 6/6 trials: high plus highest."""
    result = evaluate_numeric_support("1,299,278 hectares", SAO_PAULO_TIERS, TOLERANCE)
    assert result["support"] == "supported", result["explanation"]


def test_h6_single_measure_column_gains_no_cross_column_candidate():
    """One column has nothing to combine; the candidate set must not grow."""
    single = json.dumps(
        [
            {
                "type": "bar",
                "data": [
                    {"year": 2001, "loss_ha": 10.0},
                    {"year": 2002, "loss_ha": 20.0},
                ],
            }
        ]
    )
    values = chart_candidate_values(single)
    # leaves 10, 20; column sum 30; column max 20; and no spurious extras
    assert sorted(set(values)) == [10.0, 20.0, 30.0]


def test_h6_label_columns_are_excluded_from_cross_column_sums():
    """`year` must not be added into a measure total."""
    values = chart_candidate_values(SAO_PAULO_TIERS)
    assert not any(abs(v - (2024 + 291_728.59)) < 0.01 for v in values)


# ------------------------------------ dashboard_widgets_valid: empty dashboards


def test_h7_empty_dashboard_abstains_when_no_widgets_were_expected():
    """1-096's prompt is only 'Create a dashboard for brazil': nothing was asked
    to be in it, so an empty dashboard is not a defect."""
    result = evaluate_dashboard_widgets({"widgets": []}, None)
    assert result["dashboard_widgets_valid_score"] is None


def test_h7_empty_dashboard_still_fails_when_widgets_were_expected():
    """When the case expected widgets, an empty dashboard still fails."""
    result = evaluate_dashboard_widgets({"widgets": []}, ["map"])
    assert result["dashboard_widgets_valid_score"] == 0.0
    assert result["dashboard_widgets_match_score"] == 0.0


def test_h7_populated_widgets_are_validated_either_way():
    good = {"widgets": [{"widget_type": "text", "config": {"text": "hi"}}]}
    assert (
        evaluate_dashboard_widgets(good, None)["dashboard_widgets_valid_score"] == 1.0
    )
    bad = {"widgets": [{"widget_type": "text", "config": {}}]}
    assert evaluate_dashboard_widgets(bad, None)["dashboard_widgets_valid_score"] == 0.0


def test_h7_no_dashboard_at_all_is_still_not_applicable():
    result = evaluate_dashboard_widgets(None, ["map"])
    assert result["dashboard_widgets_valid_score"] is None
    assert result["dashboard_widgets_match_score"] is None
