"""Data pull evaluator."""

from typing import Any, Dict

from evals.evaluators.llm_judges import llm_judge_clarification
from evals.evaluators.utils import normalize_value


def evaluate_data_pull(
    agent_state: Dict[str, Any],
    min_rows: int = 1,
    expected_start_date: str = None,
    expected_end_date: str = None,
    query: str = "",
) -> Dict[str, Any]:
    """
    Check if data was successfully pulled, or if the agent asked for clarification.

    Args:
        agent_state: Final agent state after execution
        min_rows: Minimum number of rows expected
        expected_start_date: Expected start date
        expected_end_date: Expected end date
        query: Original user query for clarification detection

    Returns:
        Dict with pull_data_score (0 or 1), row_count, min_rows, data_pull_success, date_success
    """
    raw_data = agent_state.get("raw_data")

    # Check if agent asked for clarification instead of pulling data
    if not raw_data and query:
        clarification = llm_judge_clarification(agent_state, query)
        if clarification["is_clarification"]:
            return {
                "pull_data_score": 1.0,
                "row_count": 0,
                "min_rows": min_rows,
                "data_pull_success": True,  # Treat clarification as success
                "date_success": True,
                "actual_start_date": f"CLARIFICATION_REQUEST: {clarification['explanation']}",
                "actual_end_date": "CLARIFICATION_REQUEST",
                "error": "",
            }

    if not raw_data:
        return {
            "pull_data_score": 0,
            "row_count": 0,
            "min_rows": min_rows,
            "data_pull_success": False,
            "date_success": False,
            "actual_start_date": agent_state.get("start_date", ""),
            "actual_end_date": agent_state.get("end_date", ""),
            "error": "Error pulling data",
        }

    row_count = len(raw_data)
    data_pull_success = row_count >= min_rows

    # Get actual dates from agent state
    actual_start_date = agent_state.get("start_date", "")
    actual_end_date = agent_state.get("end_date", "")

    # Additive scoring: data pull success = 0.75, date success = 0.25
    pull_score = 0.75 if data_pull_success else 0

    if expected_start_date and expected_end_date:
        # Normalize date values for comparison
        expected_start_str = normalize_value(expected_start_date)
        expected_end_str = normalize_value(expected_end_date)
        actual_start_str = normalize_value(actual_start_date)
        actual_end_str = normalize_value(actual_end_date)

        date_success = (
            expected_start_str == actual_start_str
            and expected_end_str == actual_end_str
        )
        date_score = 0.25 if date_success else 0
    else:
        date_success = True
        date_score = 0.25  # Treat missing expected dates as positive match

    score = pull_score + date_score

    return {
        "pull_data_score": score,
        "row_count": row_count,
        "min_rows": min_rows,
        "data_pull_success": data_pull_success,
        "date_success": date_success,
        "actual_start_date": actual_start_date,
        "actual_end_date": actual_end_date,
        "error": "",
    }
