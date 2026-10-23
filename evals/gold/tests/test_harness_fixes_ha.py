"""Regression tests for evaluator bugs that failed correct agent answers.

Each fixture comes from the case whose staging run exposed the bug:

- `parse_expected_number` dropped a leading minus sign, so an expected net
  carbon sink could never match (1-055; `test_h1_*`).
- `pull_source_match` ignored `;`-separated dataset alternatives (1-003,
  1-062; `test_h2_*`).
- `evaluate_scope` ignored `;`-separated scope alternatives (1-089;
  `test_h3_*`).
- `web_fallback` treated a link to Global Forest Watch (which hosts the
  product's map tiles) as a sign of a web-sourced answer (1-095;
  `test_h8_*`).

The h numbers continue in test_harness_fixes_hb.py (h4 to h7) and are
unrelated to the h numbers in test_hardening.py.
"""

import json
from types import SimpleNamespace

from goldset.evaluators.chart_numeric import (
    evaluate_numeric_support,
    parse_expected_number,
)
from goldset.evaluators.guards import evaluate_guards
from goldset.evaluators.scope_checks import evaluate_scope

TOLERANCE = 0.02


# -------------------------------------------- parse_expected_number: minus sign


def test_h1_negative_expected_number_keeps_its_sign():
    """1-055 expects a net *sink*: -286,994 Mg CO2e. The sign is the capability."""
    parsed = parse_expected_number("-286,994 Mg CO2e")
    assert parsed is not None
    assert parsed.value == -286_994.0


def test_h1_negative_expected_matches_the_charts_own_net_flux():
    """The chart's net-flux series held -286,993.69 all along: a 0.0001% match
    that the unsigned parse rejected in favour of a far-off gross-emissions bar."""
    charts = json.dumps(
        [
            {
                "type": "bar",
                "data": [
                    {"metric": "gross_emissions", "value": 37_436.76},
                    {"metric": "gross_removals", "value": -324_430.45},
                    {"metric": "net_flux", "value": -286_993.69},
                ],
            },
        ],
    )
    result = evaluate_numeric_support("-286,994 Mg CO2e", charts, TOLERANCE)
    assert result["support"] == "supported", result["explanation"]
    assert result["closest_value"] == -286_993.69


def test_h1_hyphen_inside_a_word_is_not_a_minus_sign():
    """1-104's expectation mentions "Sentinel-2"; that 2 is positive."""
    parsed = parse_expected_number("Sentinel-2 scenes: 5 hectares")
    assert parsed is not None
    assert parsed.value > 0


def test_h1_year_range_still_abstains():
    """1-052 expects '2015-2020'. A year is not a measurement, signed or not."""
    assert parse_expected_number("2015-2020") is None


def test_h1_negative_ambiguous_decimal_still_abstains():
    """The sign must not smuggle a value past the ambiguous-separator guard."""
    assert parse_expected_number("-230.003") is None


# -------------------------------------------- pull_source_match: ; alternatives


def _pull_state(dataset_id: int) -> dict:
    return {
        "messages": [],
        "charts_data": [],
        "statistics": {"dataset_id": dataset_id, "data": [1], "source_url": "x"},
        "dataset": {"dataset_id": dataset_id},
    }


def test_h2_pull_source_accepts_either_alternative():
    """An expectation may list `;`-separated alternative datasets; any one of
    them satisfies the guard. The fixture uses `0;11`, the pair 1-003 once
    accepted."""
    for dataset_id in (0, 11):
        result = evaluate_guards(
            _pull_state(dataset_id),
            expects_data_pull=True,
            expected_answer="",
            expected_dataset_id="0;11",
        )
        assert result["pull_source_match_score"] == 1.0, dataset_id


def test_h2_pull_source_still_fails_a_dataset_outside_the_set():
    result = evaluate_guards(
        _pull_state(4),
        expects_data_pull=True,
        expected_answer="",
        expected_dataset_id="0;11",
    )
    assert result["pull_source_match_score"] == 0.0


def test_h2_single_value_expectation_is_unchanged():
    """The common case must not shift while fixing the alternatives case."""
    assert (
        evaluate_guards(
            _pull_state(11),
            expects_data_pull=True,
            expected_answer="",
            expected_dataset_id="11",
        )["pull_source_match_score"]
        == 1.0
    )
    assert (
        evaluate_guards(
            _pull_state(4),
            expects_data_pull=True,
            expected_answer="",
            expected_dataset_id="11",
        )["pull_source_match_score"]
        == 0.0
    )


def test_h2_dataset_id_zero_is_a_real_registry_id():
    """Dataset id 0 is a real id, not "no expectation". A falsy check treated
    it as missing, which gave 1-088 a failure on every run that was not the
    agent's fault. (Dataset 0, DIST-ALERT, is retired in the agent but still
    appears in parked cases and older runs.)"""
    assert (
        evaluate_guards(
            _pull_state(0),
            expects_data_pull=True,
            expected_answer="",
            expected_dataset_id="0",
        )["pull_source_match_score"]
        == 1.0
    )


# ----------------------------------------------- evaluate_scope: ; alternatives


def test_h3_scope_accepts_alternatives():
    """1-089's `text` allows two behaviours: refuse outright, or caution and
    offer the annual dataset through a nudge. Both must pass.

    The alternative is `refuse;suggest`, not `refuse;clarify`, because
    `classify_scope` counts a `dataset_choice` nudge as `suggest` (see
    test_harness_fixes_hb.py) and 1-089's nudge offers datasets ("Tree cover
    loss"). Changing either rule changes what 1-089 should expect.
    """
    refused = {"statistics": None, "suggested_datasets": [], "nudge": {}}
    cautioned = {
        "statistics": None,
        "suggested_datasets": [],
        "nudge": {"type": "dataset_choice"},
    }
    for state in (refused, cautioned):
        assert evaluate_scope(state, "refuse;suggest")["scope_match_score"] == 1.0


def test_h3_alternatives_accept_an_aoi_clarification():
    """The `clarify` class still exists for aoi_choice-shaped nudges."""
    state = {
        "statistics": None,
        "suggested_datasets": [],
        "nudge": {"type": "aoi_choice"},
    }
    assert evaluate_scope(state, "analyse;clarify")["scope_match_score"] == 1.0


def test_h3_scope_alternatives_still_reject_an_unlisted_class():
    analysed = {"statistics": {"data": [1]}, "suggested_datasets": [], "nudge": {}}
    assert evaluate_scope(analysed, "refuse;suggest")["scope_match_score"] == 0.0


def test_h3_single_scope_is_unchanged():
    analysed = {"statistics": {"data": [1]}, "suggested_datasets": [], "nudge": {}}
    assert evaluate_scope(analysed, "analyse")["scope_match_score"] == 1.0
    assert evaluate_scope(analysed, "refuse")["scope_match_score"] == 0.0


def test_h3_invalid_alternative_still_abstains():
    """A typo in one alternative must abstain loudly, not silently pass."""
    analysed = {"statistics": {"data": [1]}, "suggested_datasets": [], "nudge": {}}
    result = evaluate_scope(analysed, "analyse;bogus")
    assert result["scope_match_score"] is None
    assert "bogus" in (result["actual_scope"] or "")


# ---------------------------------------- web_fallback: the product's own links


def _answer_state(answer: str) -> dict:
    return {
        "messages": [SimpleNamespace(content=answer)],
        "charts_data": [{"type": "bar"}],
        "statistics": {"dataset_id": 4, "data": [1], "source_url": "x"},
        "dataset": {"dataset_id": 4},
    }


def test_h8_own_tile_domain_is_not_web_fallback():
    """1-095 answered from a real data pull and linked a Global Forest Watch
    dashboard for the same figures. A link to the product's own domains is
    not evidence of a web-sourced answer."""
    state = _answer_state(
        "Finland lost 241,368.24 hectares in 2025 at a 10% canopy threshold. "
        "See also https://www.globalforestwatch.org/dashboards/country/FIN/ "
        "for the same figures." + " padding" * 10,
    )
    result = evaluate_guards(
        state, expects_data_pull=True, expected_answer="x", expected_dataset_id="4"
    )
    assert result["web_fallback_score"] == 1.0


def test_h8_wri_org_citation_still_fires():
    """A wri.org link in an answer to a data question means the agent answered
    from a WRI blog post instead of pulling data (1-030), so `web_fallback`
    must still flag it."""
    state = _answer_state(
        "Ziguinchor has the most mangroves in Senegal, per "
        "https://www.wri.org/insights/mangrove-restoration." + " padding" * 10,
    )
    result = evaluate_guards(
        state, expects_data_pull=True, expected_answer="x", expected_dataset_id="4"
    )
    assert result["web_fallback_score"] == 0.0
    assert "wri.org" in (result["actual_web_links"] or "")


# ---------------------------------- parse_expected_number: trailing punctuation


def test_h1_a_year_followed_by_a_comma_still_abstains():
    """A leading year followed by a comma ("In 2020, 25.5 Mha") must abstain,
    as the same string without the comma does. The bug let "2020," slip past
    the year guard and become an expected value of 2020 hectares. A leading
    year makes the claim ambiguous, so the check abstains rather than guess
    which number is the answer.
    """
    assert parse_expected_number("In 2020, 25.5 Mha of loss") is None
    assert parse_expected_number("In 2020 25.5 Mha of loss") is None
    # the bare year, with or without trailing punctuation, is not a measurement
    assert parse_expected_number("2020") is None
    assert parse_expected_number("2020,") is None
    assert parse_expected_number("2020.") is None


def test_h1_thousands_separators_still_parse():
    """The trailing-punctuation strip must not damage normal figures."""
    assert parse_expected_number("1,299,278 hectares").value == 1_299_278.0
    assert parse_expected_number("25.54 million hectares").value == 25_540_000.0
    assert parse_expected_number("679.17 ha").value == 679.17
