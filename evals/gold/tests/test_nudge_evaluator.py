"""Unit tests for the nudge evaluator.

Covers the generic `nudge` state field ({type, options}) introduced in
wri/project-zeno#770, which replaces suggested_datasets and generalises
pick_aoi/pick_dataset disambiguation and the standalone send_nudge tool.
"""

from goldset.eval_types import ExpectedData
from goldset.evaluators.nudge_evaluator import evaluate_nudge


def test_nudge_evaluator_no_expectation():
    """No expected_nudge_type/options means the score abstains, but the
    actuals are still extracted: multi-turn delta snapshots and triage
    need them on turns with no nudge expectation."""
    result = evaluate_nudge(
        agent_state={"nudge": {"type": "aoi_choice", "options": ["A", "B"]}},
        expected_nudge_type=None,
        expected_nudge_options=None,
    )

    assert result["nudge_match_score"] is None
    assert result["actual_nudge_type"] == "aoi_choice"
    assert result["actual_nudge_options"] == "A; B"


def test_nudge_evaluator_type_and_options_match():
    """Exact type and option-set match scores 1.0."""
    agent_state = {
        "nudge": {
            "type": "dataset_choice",
            "options": [
                "Tree cover loss",
                "Global all ecosystem disturbance alerts (DIST-ALERT)",
            ],
        },
    }

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type="dataset_choice",
        expected_nudge_options=[
            "Tree cover loss",
            "Global all ecosystem disturbance alerts (DIST-ALERT)",
        ],
    )

    assert result["nudge_match_score"] == 1.0
    assert result["actual_nudge_type"] == "dataset_choice"
    assert (
        result["actual_nudge_options"]
        == "Tree cover loss; Global all ecosystem disturbance alerts (DIST-ALERT)"
    )


def test_nudge_evaluator_type_mismatch():
    """A different nudge type than expected scores 0.0, even if options match."""
    agent_state = {"nudge": {"type": "clarify", "options": ["A", "B"]}}

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type="aoi_choice",
        expected_nudge_options=["A", "B"],
    )

    assert result["nudge_match_score"] == 0.0
    assert result["actual_nudge_type"] == "clarify"


def test_nudge_evaluator_type_match_case_insensitive():
    """Type comparison is case-insensitive."""
    agent_state = {"nudge": {"type": "AOI_Choice", "options": []}}

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type="aoi_choice",
        expected_nudge_options=None,
    )

    assert result["nudge_match_score"] == 1.0


def test_nudge_evaluator_type_accepts_semicolon_separated_alternatives():
    """expected_nudge_type may list multiple acceptable values, semicolon-separated.

    pick_aoi/pick_dataset's nudge type is itself LLM-phrased and observed to
    vary between calls (e.g. "aoi_choice" vs "clarify_aoi" for the same
    underlying disambiguation), so a test row can list every value seen.
    """
    agent_state = {"nudge": {"type": "clarify_aoi", "options": []}}

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type="aoi_choice;clarify_aoi",
        expected_nudge_options=None,
    )

    assert result["nudge_match_score"] == 1.0

    agent_state_no_match = {"nudge": {"type": "something_else", "options": []}}
    result_no_match = evaluate_nudge(
        agent_state=agent_state_no_match,
        expected_nudge_type="aoi_choice;clarify_aoi",
        expected_nudge_options=None,
    )

    assert result_no_match["nudge_match_score"] == 0.0


def test_nudge_evaluator_options_match_by_substring_not_exact_equality():
    """Option wording drift (extra annotations) shouldn't fail the check.

    e.g. "Tree cover loss (annual)" should satisfy an expectation of just
    "Tree cover loss", and a short canonical place name like "Odisha, India"
    should satisfy a longer LLM-phrased variant like
    "Puri, Odisha, India (District)".
    """
    agent_state = {
        "nudge": {
            "type": "dataset_choice",
            "options": ["Tree cover loss (annual)", "Puri, Odisha, India (District)"],
        },
    }

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type="dataset_choice",
        expected_nudge_options=["Tree cover loss", "Odisha, India"],
    )

    assert result["nudge_match_score"] == 1.0


def test_nudge_evaluator_options_partial_valid_subset():
    """Offering a non-empty subset of the expected options is enough to pass.

    Mirrors evaluate_suggested_datasets: at least one match, none outside
    the expected set (e.g. the puri aoi_choice example only needs to offer
    a subset of the known valid locations, not all of them).
    """
    agent_state = {
        "nudge": {
            "type": "aoi_choice",
            "options": ["Puri, Odisha, India - (district-county) [IND]"],
        },
    }

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type="aoi_choice",
        expected_nudge_options=[
            "Puri, Puri, Uíge, Angola - (municipality) [AGO]",
            "Puri, Uíge, Angola - (district-county) [AGO]",
            "Puri, Odisha, India - (district-county) [IND]",
            "Puri, Puri, Odisha, India - (municipality) [IND]",
        ],
    )

    assert result["nudge_match_score"] == 1.0


def test_nudge_evaluator_options_outside_expected_set():
    """An offered option outside the expected set fails, even with overlap."""
    agent_state = {
        "nudge": {
            "type": "dataset_choice",
            "options": ["Tree cover loss", "Some unexpected dataset"],
        },
    }

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type="dataset_choice",
        expected_nudge_options=["Tree cover loss", "DIST-ALERT"],
    )

    assert result["nudge_match_score"] == 0.0


def test_nudge_evaluator_no_nudge_in_state():
    """Missing `nudge` state entirely fails when a nudge is expected."""
    result = evaluate_nudge(
        agent_state={"messages": []},
        expected_nudge_type="clarify",
        expected_nudge_options=["Option A", "Option B"],
    )

    assert result["nudge_match_score"] == 0.0
    assert result["actual_nudge_type"] is None
    assert result["actual_nudge_options"] is None


def test_nudge_evaluator_type_only_no_expected_options():
    """When only a type is expected, any options offered are acceptable."""
    agent_state = {"nudge": {"type": "clarify", "options": ["Anything", "Goes"]}}

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type="clarify",
        expected_nudge_options=None,
    )

    assert result["nudge_match_score"] == 1.0


def test_nudge_evaluator_options_only_no_expected_type():
    """When only options are expected, any nudge type is acceptable."""
    agent_state = {"nudge": {"type": "clarify", "options": ["Option A", "Option B"]}}

    result = evaluate_nudge(
        agent_state=agent_state,
        expected_nudge_type=None,
        expected_nudge_options=["Option A", "Option B"],
    )

    assert result["nudge_match_score"] == 1.0


def test_expected_data_parses_semicolon_separated_nudge_options():
    """Case files list alternative nudge options as one `;`-separated string."""
    expected = ExpectedData(
        expected_nudge_type="dataset_choice",
        expected_nudge_options="Tree cover loss;Global all ecosystem disturbance alerts (DIST-ALERT)",
    )

    assert expected.expected_nudge_options == [
        "Tree cover loss",
        "Global all ecosystem disturbance alerts (DIST-ALERT)",
    ]


def test_expected_data_empty_nudge_options_defaults_to_empty_list():
    """Empty string input parses to an empty list, not a truthy value."""
    expected = ExpectedData(expected_nudge_options="")

    assert expected.expected_nudge_options == []


def test_overall_score_includes_nudge_match_score():
    """Overall score calculation includes nudge_match_score when expected."""
    from goldset.runner.api import APITestRunner

    runner = APITestRunner(api_base_url="http://test", api_token="test")

    evaluations = {
        "aoi_id_match_score": None,
        "dataset_id_match_score": None,
        "context_layer_match_score": None,
        "data_pull_exists_score": None,
        "date_coverage_score": None,
        "charts_answer_score": None,
        "agent_answer_score": None,
        "expected_text_match_score": None,
        "clarification_requested_score": None,
        "suggested_datasets_match_score": None,
        "nudge_match_score": 1.0,
    }

    expected_data = ExpectedData(
        expected_nudge_type="dataset_choice",
        expected_nudge_options=["Tree cover loss"],
    )

    score = runner._calculate_overall_score(evaluations, expected_data)

    assert score == 1.0


def test_nudge_and_clarification_run_independently():
    """Integration: nudge is a deterministic substitute alongside clarification.

    A test row can express its expectation via expected_nudge_type/options
    instead of relying solely on the fuzzy expected_clarification LLM judge -
    both evaluations run and are reported, but only nudge is exact.
    """
    from unittest.mock import patch

    from goldset.runner.api import APITestRunner

    runner = APITestRunner(api_base_url="http://test", api_token="test")

    agent_state = {
        "nudge": {"type": "aoi_choice", "options": ["Puri, Odisha, India"]},
        "messages": [
            type(
                "obj",
                (object,),
                {"content": "I found multiple locations named Puri. Which one?"},
            )(),
        ],
    }

    expected_data = ExpectedData(
        expected_nudge_type="aoi_choice",
        expected_nudge_options=["Puri, Odisha, India"],
    )

    with patch(
        "goldset.evaluators.clarification_evaluator.llm_judge_clarification",
    ) as mock_clarif:
        mock_clarif.return_value = {
            "is_clarification": True,
            "explanation": "asking which Puri",
        }

        evaluations = runner._run_evaluations(
            agent_state,
            expected_data,
            query="search for areas named puri",
        )

        assert evaluations["nudge_match_score"] == 1.0
        assert evaluations["actual_nudge_type"] == "aoi_choice"
        # expected_clarification wasn't set on this row, so it's not scored -
        # nudge_match_score is the precise signal in this case.
        assert evaluations["clarification_requested_score"] is None
