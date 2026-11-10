"""Unit tests for the deterministic chart numeric check.

Fixtures come from real cases wherever possible, so a regression here is a
regression against something the suite actually scores.
"""

import json

from goldset.evaluators.chart_numeric import (
    chart_candidate_values,
    evaluate_numeric_support,
    parse_expected_number,
)

TOLERANCE = 0.02

# gold 1-076: 25 yearly values of intact forest loss for Russia, summing to 25.31 Mha
RUSSIA_YEARLY = json.dumps(
    [
        {
            "type": "bar",
            "data": [
                {"year": 2001 + i, "loss_ha": value}
                for i, value in enumerate([1_012_358.4] * 25)
            ],
        },
    ],
)

# gold 1-006: disturbance drivers in Occitanie; crop management is 8.41% of the total
OCCITANIE_DRIVERS = json.dumps(
    [
        {
            "type": "pie",
            "data": [
                {"driver": "Crop management", "area_ha": 427.15},
                {"driver": "Flooding", "area_ha": 2_100.0},
                {"driver": "Other", "area_ha": 2_552.75},
            ],
        },
    ],
)


def test_parses_plain_hectares():
    """The commonest shape in expected answers: a figure with thousands
    separators."""
    parsed = parse_expected_number("13,359.47 hectares")
    assert parsed is not None
    assert parsed.value == 13_359.47
    assert parsed.is_percent is False


def test_unit_multiplier_scales_into_chart_units():
    """Charts encode hectares; expected answers sometimes use Mha or kha."""
    assert parse_expected_number("25 Mha").value == 25_000_000
    assert parse_expected_number("211 kha").value == 211_000


def test_written_scale_words_are_applied():
    """Expected answers write '25.54 million hectares' as often as '25 Mha'.

    Missing this reported gold 1-059, 1-079 and 1-103 as differences of tens of millions
    of percent, failing three rows whose charts were right.
    """
    assert parse_expected_number("25.54 million hectares").value == 25_540_000
    assert parse_expected_number("123.94 million tCO2e").value == 123_940_000
    assert parse_expected_number("590 thousand ha").value == 590_000
    assert parse_expected_number("1.5 billion tonnes").value == 1_500_000_000


def test_scale_word_and_unit_prefix_agree():
    """Both spellings of the same quantity must parse to the same number."""
    assert (
        parse_expected_number("25 million hectares").value
        == parse_expected_number("25 Mha").value
    )


def test_indonesian_unit_is_recognised():
    """Gold carries multilingual rows, so 'hektar' has to resolve."""
    assert parse_expected_number("15444 hektar").value == 15_444


def test_parses_a_percentage():
    """A percentage expectation is compared against shares, not areas."""
    parsed = parse_expected_number("8.57%")
    assert parsed is not None
    assert parsed.value == 8.57
    assert parsed.is_percent is True


def test_parses_figure_embedded_in_a_named_entity_answer():
    """Gold 1-088 carries both an entity and a figure; the figure is checkable."""
    parsed = parse_expected_number("Natural short vegetation (507,742 ha)")
    assert parsed is not None
    assert parsed.value == 507_742


def test_year_is_not_a_numeric_claim():
    """Gold 1-044 expects '2003'; comparing it against areas would be nonsense."""
    assert parse_expected_number("2003") is None


def test_named_entity_is_not_a_numeric_claim():
    """Nothing to compare, so the judge's verdict stands alone."""
    assert parse_expected_number("Waikato") is None
    assert parse_expected_number("") is None


def test_ambiguous_decimal_separator_is_skipped():
    """Gold 1-093's '230.003 hektar' could be 230,003 or 230.003: don't guess."""
    assert parse_expected_number("230.003 hektar") is None


def test_zero_expected_value_is_skipped():
    """A relative difference against zero is undefined."""
    assert parse_expected_number("0 hectares") is None


def test_column_total_is_a_candidate_figure():
    """A chart of yearly values supports a period total it never draws."""
    candidates = chart_candidate_values(RUSSIA_YEARLY)
    assert any(abs(value - 25_308_960) < 1_000 for value in candidates)


def test_year_column_is_not_summed():
    """Summing 2001..2025 gives 50,325, which must not become a candidate."""
    assert not any(
        abs(value - 50_325) < 1 for value in chart_candidate_values(RUSSIA_YEARLY)
    )


def test_percent_shares_are_derived_only_when_asked_for():
    """Shares are noise unless the expectation is a percentage."""
    assert not any(
        abs(value - 8.409) < 0.01 for value in chart_candidate_values(OCCITANIE_DRIVERS)
    )
    shares = chart_candidate_values(OCCITANIE_DRIVERS, is_percent=True)
    assert any(abs(value - 8.409) < 0.01 for value in shares)


def test_malformed_chart_json_yields_no_candidates():
    """Rows with no chart at all must not raise on the way to a score."""
    assert chart_candidate_values("not json") == []
    assert chart_candidate_values("") == []


def test_period_total_within_tolerance_is_supported():
    """Gold 1-076: expected 25 Mha against a 25.31 Mha column total is 1.2% off."""
    result = evaluate_numeric_support("25 Mha", RUSSIA_YEARLY, TOLERANCE)
    assert result["support"] == "supported"
    assert result["difference"] < TOLERANCE
    assert "within the 2% tolerance" in result["explanation"]


def test_confabulated_total_is_caught():
    """The judge claimed this chart summed to 27.4 Mha. It sums to 25.31 Mha."""
    result = evaluate_numeric_support("27.4 Mha", RUSSIA_YEARLY, TOLERANCE)
    assert result["support"] == "unsupported"
    assert result["difference"] > TOLERANCE


def test_percentage_share_within_tolerance_is_supported():
    """Gold 1-006: 8.41% of the total against an expected 8.57% is 1.87% off."""
    result = evaluate_numeric_support("8.57%", OCCITANIE_DRIVERS, TOLERANCE)
    assert result["support"] == "supported"
    assert "%" in result["explanation"]


def test_percentage_outside_tolerance_is_unsupported():
    """The share is nowhere near 12%, so the chart cannot support it."""
    result = evaluate_numeric_support("12%", OCCITANIE_DRIVERS, TOLERANCE)
    assert result["support"] == "unsupported"


def test_rows_with_no_numeric_claim_defer_to_the_judge():
    """Three-valued on purpose: None means 'nothing to check here'."""
    for expected in ("2003", "Waikato", "", "230.003 hektar"):
        result = evaluate_numeric_support(expected, RUSSIA_YEARLY, TOLERANCE)
        assert result["support"] is None
        assert result["explanation"] == ""


def test_empty_chart_cannot_support_a_figure():
    """No chart data is unsupported, not unmeasured."""
    result = evaluate_numeric_support("500 ha", "[]", TOLERANCE)
    assert result["support"] == "unsupported"
    assert "no figure to compare" in result["explanation"]


def test_explanation_states_both_values_for_audit():
    """The explanation becomes the check's reason in the ledger and reports, so
    it must state both the expected and the measured value."""
    result = evaluate_numeric_support("25 Mha", RUSSIA_YEARLY, TOLERANCE)
    assert "25,000,000" in result["explanation"]
    assert "25,308,960" in result["explanation"]
