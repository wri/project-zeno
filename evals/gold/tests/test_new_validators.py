"""Tests for the deterministic per-bucket validators.

Test-name prefixes map to checks: a2 `class_value_match` and a3
`chart_integrity` (analysis bucket), e1 `answer_traceability` (explanation),
o2 `chart_well_formed` and o3 `chart_type_match` (output), s1 `scope_match`
(scope).

Fixtures copy the shape of the staging results that exposed each failure
(1-027, 1-060, 1-085).
"""

from types import SimpleNamespace

from goldset.evaluators.analysis_checks import (
    evaluate_chart_integrity,
    evaluate_class_values,
    parse_class_values,
)
from goldset.evaluators.explanation_checks import (
    evaluate_answer_traceability,
    first_bold_claim,
)
from goldset.evaluators.output_checks import (
    evaluate_chart_type,
    evaluate_chart_well_formed,
)
from goldset.evaluators.scope_checks import classify_scope, evaluate_scope

# 1-027's shape: pie of Natural vs Non-natural; prose asserts a figure that
# appears nowhere in the chart (not as leaf, sum, max, or share).
CHART_1_027 = {
    "type": "pie",
    "xAxis": "category",
    "yAxis": "area_ha",
    "data": [
        {"category": "Natural", "area_ha": 2123.927506951319},
        {"category": "Non-natural", "area_ha": 123810.96629466252},
    ],
}

# 1-060's shape: two unrelated tables zipped row-wise; the pie's own axis
# fields are null in the padded tail records.
CHART_1_060 = {
    "type": "pie",
    "xAxis": "driver_class",
    "yAxis": "para_area_ha",
    "data": [
        {
            "ranking_state": "Pará",
            "ranking_area_ha": 15000438.4,
            "driver_class": "Permanent agriculture",
            "para_area_ha": 15000438.4,
        },
        {
            "ranking_state": "Mato Grosso",
            "ranking_area_ha": 12000000.0,
            "driver_class": "Shifting cultivation",
            "para_area_ha": 900000.0,
        },
        {
            "ranking_state": "Rondônia",
            "ranking_area_ha": 4897042.0,
            "driver_class": None,
            "para_area_ha": None,
        },
    ],
}


def state(charts=None, prose=None, stats=None, suggested=None, nudge=None):
    return {
        "charts_data": charts or [],
        "messages": [SimpleNamespace(content=prose)] if prose else [],
        "statistics": stats if stats is not None else [],
        "suggested_datasets": suggested or [],
        "nudge": nudge or {},
    }


# --- class_value_match


def test_a2_matches_named_class_value_within_tolerance():
    result = evaluate_class_values(
        state(charts=[CHART_1_027]), "Natural=2,124 hectares"
    )
    assert result["class_value_match_score"] == 1.0


def test_a2_fails_on_wrong_subtotal_and_missing_class():
    wrong = evaluate_class_values(state(charts=[CHART_1_027]), "Natural=5,000 ha")
    assert wrong["class_value_match_score"] == 0.0
    missing = evaluate_class_values(state(charts=[CHART_1_027]), "Wetlands=99 ha")
    assert missing["class_value_match_score"] == 0.0
    assert "no matching record" in missing["actual_class_values"]


def test_a2_no_data_fails_and_ambiguity_abstains():
    assert (
        evaluate_class_values(state(), "Natural=5 ha")["class_value_match_score"] == 0.0
    )
    # locale-ambiguous decimal: abstain, never guess (chart_numeric rule)
    ambiguous = evaluate_class_values(state(charts=[CHART_1_027]), "Natural=230.003")
    assert ambiguous["class_value_match_score"] is None
    assert parse_class_values("no-equals-sign") is None


# --- chart_integrity


def test_a3_null_padded_axis_fields_fail():
    result = evaluate_chart_integrity(state(charts=[CHART_1_060]))
    assert result["chart_integrity_score"] == 0.0
    assert "mis-joined" in result["chart_integrity_reason"]
    assert "driver_class" in result["chart_integrity_reason"]


def test_a3_clean_chart_passes_and_no_chart_abstains():
    assert (
        evaluate_chart_integrity(state(charts=[CHART_1_027]))["chart_integrity_score"]
        == 1.0
    )
    assert evaluate_chart_integrity(state())["chart_integrity_score"] is None


# --- answer_traceability


def test_e1_catches_1_027_untraceable_figure():
    prose = "There are approximately **679.16 hectares** of natural short vegetation."
    result = evaluate_answer_traceability(state(charts=[CHART_1_027], prose=prose))
    assert result["answer_traceability_score"] == 0.0
    assert "679" in result["actual_traceability_claim"]


def test_e1_traceable_figure_passes_via_leaf_and_sum():
    leaf = "The natural area is **2,123.93 hectares** in total."
    assert (
        evaluate_answer_traceability(state(charts=[CHART_1_027], prose=leaf))[
            "answer_traceability_score"
        ]
        == 1.0
    )
    total = "Overall **125,934.89 hectares** were assessed."  # sum of both slices
    assert (
        evaluate_answer_traceability(state(charts=[CHART_1_027], prose=total))[
            "answer_traceability_score"
        ]
        == 1.0
    )


def test_e1_abstains_without_bold_claim_or_charts():
    no_bold = evaluate_answer_traceability(
        state(charts=[CHART_1_027], prose="about 679.16 hectares, unbolded")
    )
    assert no_bold["answer_traceability_score"] is None
    assert "no bolded numeric claim" in no_bold["answer_traceability_reason"]
    assert first_bold_claim("**in 2022** things happened") is None  # year skipped
    assert (
        evaluate_answer_traceability(state(prose="**42 ha**"))[
            "answer_traceability_score"
        ]
        is None
    )  # no charts


# --- chart_well_formed


def test_o2_axis_referencing_missing_field_fails():
    broken = {**CHART_1_027, "yAxis": "hectares_wrong"}
    result = evaluate_chart_well_formed(state(charts=[broken]))
    assert result["chart_well_formed_score"] == 0.0
    assert "absent from data" in result["chart_well_formed_reason"]


def test_o2_empty_data_fails_and_pie_slices_are_info_only():
    empty = {"type": "bar", "xAxis": "x", "yAxis": "y", "data": []}
    assert (
        evaluate_chart_well_formed(state(charts=[empty]))["chart_well_formed_score"]
        == 0.0
    )
    ok = evaluate_chart_well_formed(state(charts=[CHART_1_027]))
    assert ok["chart_well_formed_score"] == 1.0
    assert ok["actual_max_pie_slices"] == 2


# --- chart_type_match


def test_o3_alternatives_and_missing_chart():
    assert (
        evaluate_chart_type(state(charts=[CHART_1_027]), "pie;table")[
            "chart_type_match_score"
        ]
        == 1.0
    )
    assert (
        evaluate_chart_type(state(charts=[CHART_1_027]), "line")[
            "chart_type_match_score"
        ]
        == 0.0
    )
    assert evaluate_chart_type(state(), "pie")["chart_type_match_score"] == 0.0
    assert (
        evaluate_chart_type(state(charts=[CHART_1_027]), "")["chart_type_match_score"]
        is None
    )


# --- non-dict chart elements must never raise (guarded like inner rows)


def test_non_dict_chart_elements_are_guarded():
    charts = ["garbage", CHART_1_027]
    assert (
        evaluate_chart_integrity(state(charts=charts))["chart_integrity_score"] == 1.0
    )
    assert (
        evaluate_class_values(state(charts=charts), "Natural=2,124 ha")[
            "class_value_match_score"
        ]
        == 1.0
    )
    # well-formedness flags the junk element instead of skipping it
    well_formed = evaluate_chart_well_formed(state(charts=charts))
    assert well_formed["chart_well_formed_score"] == 0.0
    assert "not an object" in well_formed["chart_well_formed_reason"]
    # a non-dict first chart reads as "no chart type", so the expectation fails
    assert (
        evaluate_chart_type(state(charts=["garbage"]), "pie")["chart_type_match_score"]
        == 0.0
    )


# --- scope_match

PULL = [{"source_url": "https://api/x", "id": "p1", "data": [{"a": 1}]}]


def test_s1_catches_1_085_analysis_instead_of_suggestion():
    result = evaluate_scope(state(stats=PULL), "suggest")
    assert result["scope_match_score"] == 0.0
    assert result["actual_scope"] == "analyse"


def test_s1_classification_precedence_and_matches():
    assert classify_scope(state(stats=PULL, suggested=["0"])) == "analyse"
    assert classify_scope(state(suggested=["0", "11"])) == "suggest"
    assert (
        classify_scope(state(nudge={"type": "aoi_choice", "options": ["a"]}))
        == "clarify"
    )
    assert classify_scope(state(prose="I cannot help with that.")) == "none"
    assert evaluate_scope(state(suggested=["0"]), "suggest")["scope_match_score"] == 1.0
    assert evaluate_scope(state(prose="no"), "refuse")["scope_match_score"] == 1.0
    assert evaluate_scope(state(stats=PULL), "analyze")["scope_match_score"] == 1.0


def test_s1_invalid_expected_abstains():
    result = evaluate_scope(state(), "escalate")
    assert result["scope_match_score"] is None
    assert "invalid" in result["actual_scope"]


def test_e1_bare_numbers_are_not_claims():
    """Bold counts and ranks are not measures. In an early staging run,
    '**2** datasets' and 'top **5**' made up most of the false positives."""
    assert first_bold_claim("I found **2** datasets for you") is None
    assert first_bold_claim("the top **5** regions are listed") is None
    assert first_bold_claim("roughly **4,615** in total") is None
    # units, scale words and percents still qualify
    assert first_bold_claim("**679.16 hectares** of vegetation") is not None
    assert first_bold_claim("**25.5 Mha** were lost") is not None
    assert first_bold_claim("**8.57%** of the land") is not None
    assert first_bold_claim("**1.2 million hectares**") is not None
