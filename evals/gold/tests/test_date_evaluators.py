"""Unit tests for the two date checks.

`date_extraction_score` reads the start_date/end_date the agent passed to its own
tools, which is the only deterministic record of the period it was asked to analyse.
`date_coverage_score` asks whether the range recorded in agent state *covers* the
request, since the agent legitimately pulls wider and slices in code.
"""

from goldset.evaluators.data_pull_evaluator import (
    evaluate_date_extraction,
    evaluate_date_selection,
)


class StubMessage:
    """Minimal stand-in for a LangChain message carrying tool calls."""

    def __init__(self, tool_calls=None):
        """Attach tool_calls only when given, mimicking messages that have none."""
        if tool_calls is not None:
            self.tool_calls = tool_calls


def _state(*calls):
    """Build an agent_state whose messages carry the given (name, start, end) calls."""
    return {
        "messages": [
            StubMessage(
                [
                    {
                        "name": name,
                        "args": {"start_date": start, "end_date": end},
                        "id": f"call_{i}",
                    },
                ],
            )
            for i, (name, start, end) in enumerate(calls)
        ],
    }


# ---------------------------------------------------------------- extraction


def test_extraction_not_evaluated_without_expected_dates():
    result = evaluate_date_extraction(_state(("pull_data", "2022-01-01", "2022-12-31")))
    assert result["date_extraction_score"] is None
    # Actuals are still surfaced so a curator can see what the agent used.
    assert result["actual_extracted_start_date"] == "2022-01-01"
    assert result["date_extraction_source"] == "pull_data"


def test_extraction_matches_pull_data_args():
    result = evaluate_date_extraction(
        _state(("pull_data", "2022-01-01", "2022-12-31")),
        "2022-01-01",
        "2022-12-31",
    )
    assert result["date_extraction_score"] == 1.0
    assert result["date_extraction_source"] == "pull_data"


def test_extraction_passes_regardless_of_recorded_state():
    """The real-world case: params say 2022, state says the dataset's full extent.

    Reproduces gold row 1-092 - the agent extracted 2022 correctly and answered
    correctly, while agent_state recorded 2001-2025.
    """
    state = _state(("pull_data", "2022-01-01", "2022-12-31"))
    state["start_date"] = "2001-01-01"
    state["end_date"] = "2025-12-31"

    extraction = evaluate_date_extraction(state, "2022-01-01", "2022-12-31")
    coverage = evaluate_date_selection(state, "2022-01-01", "2022-12-31")

    assert extraction["date_extraction_score"] == 1.0, "the agent did read 2022"
    assert coverage["date_coverage_score"] == 1.0, "and 2001-2025 contains 2022"


def test_extraction_fails_on_wrong_window():
    result = evaluate_date_extraction(
        _state(("pull_data", "2021-01-01", "2021-12-31")),
        "2022-01-01",
        "2022-12-31",
    )
    assert result["date_extraction_score"] == 0.0
    assert result["actual_extracted_start_date"] == "2021-01-01"


def test_extraction_falls_back_to_pick_dataset():
    result = evaluate_date_extraction(
        _state(("pick_dataset", "2022-01-01", "2022-12-31")),
        "2022-01-01",
        "2022-12-31",
    )
    assert result["date_extraction_score"] == 1.0
    assert result["date_extraction_source"] == "pick_dataset"


def test_extraction_prefers_pull_data_over_pick_dataset():
    """pull_data is the actual request, so it wins when the two disagree."""
    result = evaluate_date_extraction(
        _state(
            ("pick_dataset", "2019-01-01", "2019-12-31"),
            ("pull_data", "2022-01-01", "2022-12-31"),
        ),
        "2019-01-01",
        "2019-12-31",
    )
    assert result["date_extraction_score"] == 0.0, "pick_dataset must not rescue it"
    assert result["date_extraction_source"] == "pull_data"


def test_extraction_any_matching_call_passes():
    """A row that pulls more than once is not penalised for the extra call."""
    result = evaluate_date_extraction(
        _state(
            ("pull_data", "2019-01-01", "2019-12-31"),
            ("pull_data", "2022-01-01", "2022-12-31"),
        ),
        "2022-01-01",
        "2022-12-31",
    )
    assert result["date_extraction_score"] == 1.0
    assert "2019-01-01" in result["actual_extracted_windows"], "both are recorded"


def test_extraction_scores_zero_when_agent_never_scoped_a_period():
    result = evaluate_date_extraction({"messages": []}, "2022-01-01", "2022-12-31")
    assert result["date_extraction_score"] == 0.0
    assert result["actual_extracted_windows"] is None


def test_extraction_tolerates_date_formats():
    """Tool args in M/D/YYYY still match an ISO expectation."""
    result = evaluate_date_extraction(
        _state(("pull_data", "1/1/2022", "12/31/2022")),
        "2022",
        "2022",
    )
    assert result["date_extraction_score"] == 1.0


def test_extraction_accepts_an_open_ended_request():
    """The agent omits end_date for "how much X in total" style queries.

    Observed on gold 1-076 ("How much deforestation in Russia?"), where pull_data was
    called with start_date only. Requiring both bounds failed a correct pull, so only
    the bounds the agent supplied are checked.
    """
    result = evaluate_date_extraction(
        _state(("pull_data", "2001-01-01", "")),
        "2001-01-01",
        "2025-12-31",
    )
    assert result["date_extraction_score"] == 1.0
    assert result["actual_extracted_end_date"] is None


def test_extraction_still_fails_an_open_ended_request_with_the_wrong_start():
    """Open-endedness relaxes the end bound only - a wrong start still fails."""
    result = evaluate_date_extraction(
        _state(("pull_data", "2015-01-01", "")),
        "2001-01-01",
        "2025-12-31",
    )
    assert result["date_extraction_score"] == 0.0


def test_extraction_accepts_an_end_only_request():
    result = evaluate_date_extraction(
        _state(("pull_data", "", "2022-12-31")),
        "2022-01-01",
        "2022-12-31",
    )
    assert result["date_extraction_score"] == 1.0


def test_extraction_not_evaluated_on_unparseable_expectation():
    result = evaluate_date_extraction(
        _state(("pull_data", "2022-01-01", "2022-12-31")),
        "31/12/2022",  # D/M/YYYY - unsupported
        "31/12/2022",
    )
    assert result["date_extraction_score"] is None


def test_extraction_ignores_messages_without_tool_calls():
    state = {
        "messages": [StubMessage(), StubMessage([{"name": "pick_aoi", "args": {}}])],
    }
    result = evaluate_date_extraction(state, "2022-01-01", "2022-12-31")
    assert result["date_extraction_score"] == 0.0
    assert result["date_extraction_source"] is None


# ---------------------------------------------------------------- coverage


def test_coverage_accepts_a_wider_recorded_range():
    """The reason this check exists: the agent often pulls a dataset's full
    range and slices it in code, and that covers the request."""
    state = {"start_date": "2001-01-01", "end_date": "2025-12-31"}
    result = evaluate_date_selection(state, "2022-01-01", "2022-12-31")
    assert result["date_coverage_score"] == 1.0
    assert result["date_success"] is True


def test_coverage_accepts_an_exact_range():
    state = {"start_date": "2022-01-01", "end_date": "2022-12-31"}
    assert (
        evaluate_date_selection(state, "2022-01-01", "2022-12-31")[
            "date_coverage_score"
        ]
        == 1.0
    )


def test_coverage_fails_when_the_range_misses_part_of_the_request():
    """Gold row 1-034: pulled from 2002 when 2001 was asked for, so a year is absent."""
    state = {"start_date": "2002-01-01", "end_date": "2024-12-31"}
    result = evaluate_date_selection(state, "2001-01-01", "2024-12-31")
    assert result["date_coverage_score"] == 0.0
    assert result["date_success"] is False


def test_coverage_fails_when_nothing_was_recorded():
    result = evaluate_date_selection({}, "2022-01-01", "2022-12-31")
    assert result["date_coverage_score"] == 0.0
    assert result["actual_start_date"] is None
