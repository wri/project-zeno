"""ground_truth_match / ground_truth_answer — no network, judge monkeypatched."""

from types import SimpleNamespace

import pytest

from goldset.buckets import implied_checks, row_verdict
from goldset.eval_types import ExpectedData
from goldset.evaluators import groundtruth_checks
from goldset.evaluators.groundtruth_checks import evaluate_ground_truth

SELECTOR = "sum(carbon_emissions_MgCO2e) WHERE tree_cover_loss_year=2019"
VALUE = 658496.56
PULL = {"source_url": "http://analytics.example/x", "id": "p1", "data": {}}
FULL_TABLE = {
    "tree_cover_loss_year": [2018, 2019, 2020],
    "carbon_emissions_MgCO2e": [1.0, VALUE, 3.0],
}


def expected(values=(VALUE,), selector=SELECTOR, unresolved=""):
    return ExpectedData(
        expected_ground_truth=selector,
        ground_truth_values=list(values),
        ground_truth_unresolved=unresolved,
    )


def state(pulled=None, statistics=(PULL,), charts=(), answer=""):
    return {
        "pulled_data": pulled,
        "statistics": list(statistics),
        "charts_data": list(charts),
        "messages": [SimpleNamespace(content=answer)] if answer else [],
    }


@pytest.fixture
def judge(monkeypatch):
    """Stub judge returning a fixed extraction; records its calls."""
    calls: list = []

    def install(extracted: str = "", raises: Exception | None = None):
        def fake(expected_answer, actual_answer):
            calls.append(expected_answer)
            if raises:
                raise raises
            return SimpleNamespace(extracted_number=extracted)

        monkeypatch.setattr(groundtruth_checks, "judge_answer", fake)
        return calls

    return install


# --- ground_truth_match -----------------------------------------------------


def test_full_pull_resolves_through_the_selector(judge):
    judge()
    got = evaluate_ground_truth(state(pulled=FULL_TABLE), expected())
    assert got["ground_truth_match_score"] == 1.0


def test_a_narrowed_one_row_pull_resolves_to_the_same_figure(judge):
    """1-046: the agent pulls only 2019; the WHERE still applies."""
    judge()
    pulled = {"tree_cover_loss_year": [2019], "carbon_emissions_MgCO2e": [658_400.0]}
    assert (
        evaluate_ground_truth(state(pulled=pulled), expected())[
            "ground_truth_match_score"
        ]
        == 1.0
    )


def test_a_wrong_pull_fails_even_when_a_chart_figure_matches(judge):
    judge()
    wrong = {"tree_cover_loss_year": [2019], "carbon_emissions_MgCO2e": [12.0]}
    chart = {"type": "bar", "data": [{"year": 2019, "value": VALUE}]}
    got = evaluate_ground_truth(state(pulled=wrong, charts=[chart]), expected())
    assert got["ground_truth_match_score"] == 0.0
    assert "12" in got["agent_ground_truth"]


def test_a_pull_missing_the_metric_fails(judge):
    """A misrouted pull (another dataset's columns) yields no figure at all."""
    judge()
    lgms = {"emissions": {"sector": ["forest"], "net_flux": [5.0]}}
    got = evaluate_ground_truth(state(pulled=lgms), expected())
    assert got["ground_truth_match_score"] == 0.0
    assert "gives nothing" in got["agent_ground_truth"]


def test_a_null_column_in_the_agents_pull_still_scores(judge):
    """A null column in the agent's own pull (emissions at a low canopy_cover
    threshold) is ignored, so a selector on another column still scores."""
    judge()
    pulled = {
        "tree_cover_loss_year": [2024, 2025],
        "area_ha": [198000.0, 241368.24],
        "carbon_emissions_MgCO2e": None,
    }
    got = evaluate_ground_truth(
        state(pulled=pulled),
        expected(
            values=(241368.24,), selector="sum(area_ha) WHERE tree_cover_loss_year=2025"
        ),
    )
    assert got["ground_truth_match_score"] == 1.0
    assert got["agent_ground_truth_values"] == [pytest.approx(241368.24)]


def test_sectioned_pull_is_searched_per_section(judge):
    judge()
    sectioned = {"a": {"other": [1.0]}, "b": FULL_TABLE}
    assert (
        evaluate_ground_truth(state(pulled=sectioned), expected())[
            "ground_truth_match_score"
        ]
        == 1.0
    )


def test_no_pull_at_all_fails(judge):
    judge()
    got = evaluate_ground_truth(state(statistics=()), expected())
    assert got["ground_truth_match_score"] == 0.0


def test_unreadable_pull_falls_back_to_the_chart(judge):
    judge()
    chart = {"type": "bar", "data": [{"year": 2019, "value": VALUE}]}
    assert (
        evaluate_ground_truth(state(charts=[chart]), expected())[
            "ground_truth_match_score"
        ]
        == 1.0
    )


def test_unreadable_pull_without_a_chart_match_abstains(judge):
    """Harness could not read the pull: no verdict against the agent."""
    judge()
    chart = {"type": "bar", "data": [{"year": 2019, "value": 1.0}]}
    assert (
        evaluate_ground_truth(state(charts=[chart]), expected())[
            "ground_truth_match_score"
        ]
        is None
    )


def test_zero_matches_only_zero(judge):
    judge()
    table = {"tree_cover_loss_year": [2019], "carbon_emissions_MgCO2e": [0.0]}
    assert (
        evaluate_ground_truth(state(pulled=table), expected(values=(0.0,)))[
            "ground_truth_match_score"
        ]
        == 1.0
    )
    assert (
        evaluate_ground_truth(state(pulled=FULL_TABLE), expected(values=(0.0,)))[
            "ground_truth_match_score"
        ]
        == 0.0
    )


def test_the_agent_figure_is_recorded_only_from_its_own_pull(judge):
    """diff_runs compares this against both runs' values to spot a hidden break."""
    judge()
    got = evaluate_ground_truth(state(pulled=FULL_TABLE), expected())
    assert got["agent_ground_truth_values"] == [pytest.approx(VALUE)]

    chart = {"type": "bar", "data": [{"year": 2019, "value": VALUE}]}
    lgms = {"emissions": {"sector": ["forest"], "net_flux": [5.0]}}
    for agent_state in (
        state(charts=[chart]),
        state(statistics=()),
        state(pulled=lgms),
    ):
        assert evaluate_ground_truth(agent_state, expected())[
            "agent_ground_truth_values"
        ] == [None]


def test_every_value_must_match(judge):
    judge()
    got = evaluate_ground_truth(
        state(pulled=FULL_TABLE), expected(values=(VALUE, 999.0))
    )
    assert got["ground_truth_match_score"] == 0.0


def test_unresolved_selector_is_an_error_not_a_score(judge):
    calls = judge()
    got = evaluate_ground_truth(
        state(pulled=FULL_TABLE), expected(values=(), unresolved="no rows")
    )
    assert got["error"] == "ground truth unresolved: no rows"
    assert got["ground_truth_match_score"] is None
    assert calls == []


def test_missing_values_never_pass_vacuously(judge):
    judge()
    got = evaluate_ground_truth(state(pulled=FULL_TABLE), expected(values=()))
    assert got["error"] == "ground truth was not fetched for this case"


def test_cases_without_ground_truth_are_untouched(judge):
    calls = judge(raises=AssertionError("judge must not run"))
    got = evaluate_ground_truth(
        state(pulled=FULL_TABLE, answer="658,496 t"), ExpectedData()
    )
    assert got == {"ground_truth_match_score": None, "ground_truth_answer_score": None}
    assert calls == []


# --- ground_truth_answer ----------------------------------------------------


def test_prose_figure_is_compared_in_code(judge):
    calls = judge(extracted="658,500 tonnes")
    got = evaluate_ground_truth(
        state(pulled=FULL_TABLE, answer="About 658,500 tonnes."), expected()
    )
    assert got["ground_truth_answer_score"] == 1.0
    assert SELECTOR in calls[0]


def test_prose_figure_out_of_tolerance_scores_zero(judge):
    judge(extracted="700,000 tonnes")
    assert (
        evaluate_ground_truth(
            state(pulled=FULL_TABLE, answer="700,000 tonnes"), expected()
        )["ground_truth_answer_score"]
        == 0.0
    )


def test_unparseable_extraction_abstains_instead_of_trusting_the_judge(judge):
    judge(extracted="")
    assert (
        evaluate_ground_truth(state(pulled=FULL_TABLE, answer="Lots."), expected())[
            "ground_truth_answer_score"
        ]
        is None
    )


def test_judge_outage_never_errors_the_row(judge):
    """Info-only: an outage stays out of judge_errors."""
    judge(raises=RuntimeError("503"))
    got = evaluate_ground_truth(
        state(pulled=FULL_TABLE, answer="658,500 t"), expected()
    )
    assert got["ground_truth_answer_score"] is None
    assert got["ground_truth_answer_score_reason"].startswith("JUDGE ERROR")
    assert "judge_errors" not in got and "error" not in got
    entry = {
        "checks": {
            "ground_truth_match": got["ground_truth_match_score"],
            "ground_truth_answer": 0.0,
        }
    }
    assert row_verdict(entry) == "pass"  # a failing info-only check never gates


# --- reconciliation ---------------------------------------------------------


def test_ground_truth_implies_the_match_and_a_pull():
    assert implied_checks({"ground_truth": SELECTOR}) == {
        "ground_truth_match",
        "data_pull_exists",
        "answered_without_data",
    }
    assert ExpectedData(expected_ground_truth=SELECTOR).expects_data_pull()
