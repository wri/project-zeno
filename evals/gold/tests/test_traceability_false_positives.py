"""answer_traceability false positives seen in a local GOLD run on 2026-11-16.

Each case is a correct answer that the check marked as unsupported:
- bold markers paired across list items, which read plain text as a claim;
- a bolded canopy cover threshold or confidence level read as a finding;
- a French decimal comma ("289,11") read as 28,911;
- a percent change that the agent copies from its chart facts.
"""

import json
from types import SimpleNamespace

from goldset.evaluators.chart_numeric import (
    chart_candidate_values,
    parse_expected_number,
)
from goldset.evaluators.explanation_checks import (
    evaluate_answer_traceability,
    first_bold_claim,
)


def _state(charts, prose):
    return {"charts_data": charts, "messages": [SimpleNamespace(content=prose)]}


def _tcl_chart(values):
    return {
        "title": "Annual Tree Cover Loss",
        "type": "bar",
        "xAxis": "tree_cover_loss_year",
        "yAxis": "area_ha",
        "data": [
            {"tree_cover_loss_year": 2020 + i, "area_ha": v}
            for i, v in enumerate(values)
        ],
    }


# --- bold spans -------------------------------------------------------------


def test_bold_does_not_pair_across_list_items():
    # 1-041: a stray `***` paired the markers of two list items, and the plain
    # text between them, with its "75% confidence", became the claim.
    prose = (
        "The peak year was **2003**.\n\n"
        "***Note:** Estimates are derived from the dataset. There is a 75% "
        "confidence that loss occurred within the stated year.\n"
        "*   **Next:** more"
    )
    assert first_bold_claim(prose) is None


def test_a_bold_claim_in_a_list_is_still_found():
    prose = "*   **Total loss:** **26,965 ha**\n*   **Peak:** 2023"
    assert first_bold_claim(prose) == "26,965 ha"


# --- settings ---------------------------------------------------------------


def test_a_bolded_canopy_threshold_is_not_a_claim():
    # 1-094: the threshold came before the finding in the answer.
    assert first_bold_claim("统计标准：**30% 树冠郁闭度** 的标准。") is None
    assert first_bold_claim("A threshold of **≥ 30%** canopy cover.") is None
    assert first_bold_claim("At **30% canopy cover**, loss was 5 ha.") is None


def test_a_finding_after_a_setting_is_found():
    prose = "At **30% canopy cover**, the loss was **5,051.25 ha**."
    assert first_bold_claim(prose) == "5,051.25 ha"


# --- decimal comma ----------------------------------------------------------


def test_a_french_decimal_comma_is_a_decimal():
    # 1-091: "289,11 hectares" is 289.11, not 28,911.
    assert parse_expected_number("289,11 hectares").value == 289.11
    assert parse_expected_number("1,5 Mha").value == 1_500_000


def test_a_thousands_comma_is_unchanged():
    assert parse_expected_number("28,911 hectares").value == 28_911
    assert parse_expected_number("1,234,567 ha").value == 1_234_567


def test_the_french_answer_traces_to_its_chart():
    chart = _tcl_chart([289.11])
    result = evaluate_answer_traceability(
        _state([chart], "Le Sénégal a perdu **289,11 hectares** en 2022.")
    )
    assert result["answer_traceability_score"] == 1.0


# --- percent change ---------------------------------------------------------


def test_the_first_to_last_change_is_a_percent_candidate():
    charts = json.dumps([_tcl_chart([8411.44, 8053.18, 5404.36, 6181.70, 5051.25])])
    candidates = chart_candidate_values(charts, is_percent=True)
    assert any(abs(c - (-39.95)) < 0.01 for c in candidates)
    assert any(abs(c - 39.95) < 0.01 for c in candidates)


def test_a_change_in_words_traces_to_its_chart():
    # 1-032: "39.95% lower" from the change fact of the curated chart.
    chart = _tcl_chart([8411.44, 8053.18, 5404.36, 6181.70, 5051.25])
    result = evaluate_answer_traceability(
        _state([chart], "Loss in 2024 was **39.95% lower** than in 2020.")
    )
    assert result["answer_traceability_score"] == 1.0


def test_a_percent_that_no_chart_gives_still_fails():
    chart = _tcl_chart([8411.44, 8053.18, 5404.36, 6181.70, 5051.25])
    result = evaluate_answer_traceability(
        _state([chart], "Loss fell by **12.5%** over the period.")
    )
    assert result["answer_traceability_score"] == 0.0


def test_a_subscript_co2_unit_is_a_measure():
    # 1-041: "MgCO₂e" with a subscript two.
    assert first_bold_claim("**30,612,006.65 MgCO₂e** emitted") == (
        "30,612,006.65 MgCO₂e"
    )
