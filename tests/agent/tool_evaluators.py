"""
Simple end-to-end agent evaluation functions.

Basic functions to evaluate each step of the agent workflow:
- evaluate_aoi_selection: Check if correct AOI was picked
- evaluate_dataset_selection: Check if correct dataset was picked
- evaluate_data_pull: Check if data was successfully pulled
- evaluate_final_answer: Check if final answer aligns with expected result
"""

from typing import Any, Dict, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from src.utils.llms import HAIKU


def normalize_gadm_id(gadm_id: str) -> str:
    """Normalize GADM ID for comparison."""
    if not gadm_id:
        return ""
    return gadm_id.split("_")[0].replace("-", ".").lower()


def evaluate_aoi_selection(
    agent_state: Dict[str, Any],
    expected_aoi_id: str,
    expected_subregion: Optional[str],
) -> Dict[str, Any]:
    """
    Check if the correct AOI was selected.

    Args:
        agent_state: Final agent state after execution
        expected_aoi_id: Expected AOI ID (e.g., "BRA", "USA.5_1")
        expected_subregion: Expected subregion (e.g., "state-province", "country")
    Returns:
        Dict with aoi_score (0 or 1), actual_id, actual_name, actual_subtype, actual_source
    """
    aoi = agent_state.get("aoi")
    subregion = agent_state.get("subregion")

    if not aoi or not expected_aoi_id:
        return {
            "aoi_score": 0,
            "actual_id": None,
            "actual_name": None,
            "actual_subtype": None,
            "actual_source": None,
        }

    # Get actual AOI ID based on subtype
    actual_aoi_id = aoi.get("src_id", "")
    actual_aoi_name = aoi.get("name", "")
    actual_aoi_subtype = aoi.get("subtype", "")
    actual_aoi_source = aoi.get("source", "")

    if actual_aoi_source == "gadm":
        # Normalize GADM ids
        normalized_actual = normalize_gadm_id(actual_aoi_id)
        normalized_expected = normalize_gadm_id(expected_aoi_id)
    else:
        normalized_actual = actual_aoi_id.lower()
        normalized_expected = expected_aoi_id.lower()

    match_aoi_id = normalized_actual == normalized_expected

    # Simple string comparison for subregion
    expected_subregion_str = (
        str(expected_subregion).strip() if expected_subregion else ""
    )
    actual_subregion_str = str(subregion).strip() if subregion else ""

    # If expected subregion is empty, skip subregion check
    if not expected_subregion_str:
        match_subregion = True
        score = 1 if match_aoi_id else 0
    else:
        match_subregion = expected_subregion_str == actual_subregion_str
        score = 1 if match_aoi_id and match_subregion else 0

    return {
        "aoi_score": score,
        "actual_id": actual_aoi_id,
        "actual_name": actual_aoi_name,
        "actual_subtype": actual_aoi_subtype,
        "actual_source": actual_aoi_source,
        "match_aoi_id": match_aoi_id,
        "match_subregion": match_subregion,
    }


def evaluate_dataset_selection(
    agent_state: Dict[str, Any],
    expected_dataset_id: Any,
    expected_context_layer: Any,
) -> Dict[str, Any]:
    """
    Check if the correct dataset was selected using simple string comparison.

    Args:
        agent_state: Final agent state after execution
        expected_dataset_id: Expected dataset id as string
        expected_context_layer: Expected context layer as string
    Returns:
        Dict with dataset_score (0 or 1), actual_dataset_id, actual_dataset_name, actual_context_layer
    """
    dataset = agent_state.get("dataset", {})

    if not dataset:
        return {
            "dataset_score": 0,
            "actual_dataset_id": None,
            "actual_dataset_name": None,
            "actual_context_layer": None,
            "error": "Missing dataset data",
        }

    actual_dataset_id = dataset.get("dataset_id", "")
    actual_dataset_name = dataset.get("dataset_name", "")
    actual_context_layer = dataset.get("context_layer", "")

    # Simple string comparison
    expected_id_str = str(expected_dataset_id).strip()
    actual_id_str = str(actual_dataset_id).strip()
    dataset_match = expected_id_str == actual_id_str

    expected_context_str = str(expected_context_layer).strip()
    actual_context_str = str(actual_context_layer).strip()

    # Context layer matching: if expected is empty, skip the check
    if not expected_context_str:
        context_layer_match = True
    else:
        context_layer_match = expected_context_str == actual_context_str

    score = 1 if dataset_match and context_layer_match else 0

    return {
        "dataset_score": score,
        "actual_dataset_id": actual_dataset_id,
        "actual_dataset_name": actual_dataset_name,
        "actual_context_layer": actual_context_layer,
        "error": "",
    }


def evaluate_data_pull(
    agent_state: Dict[str, Any],
    min_rows: int = 1,
    expected_start_date: str = None,
    expected_end_date: str = None,
) -> Dict[str, Any]:
    """
    Check if data was successfully pulled.

    Args:
        agent_state: Final agent state after execution
        min_rows: Minimum number of rows expected
        expected_start_date: Expected start date
        expected_end_date: Expected end date
    Returns:
        Dict with pull_data_score (0 or 1), row_count, min_rows, data_pull_success, date_success
    """
    raw_data = agent_state.get("raw_data")

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

    if expected_start_date and expected_end_date:
        # Simple string comparison for dates
        expected_start_str = str(expected_start_date).strip()
        expected_end_str = str(expected_end_date).strip()
        actual_start_str = str(actual_start_date).strip()
        actual_end_str = str(actual_end_date).strip()

        date_success = (
            expected_start_str == actual_start_str
            and expected_end_str == actual_end_str
        )
    else:
        date_success = True

    score = 1 if data_pull_success and date_success else 0

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


def llm_judge(expected_answer: str, actual_answer: str):
    class Score(BaseModel):
        score: int

    JUDGE_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """
                You are evaluating if an AI-generated insight captures the essence of an expected answer.

                EXPECTED ANSWER: {expected_answer}

                ACTUAL INSIGHT: {actual_answer}

                Does the actual insight capture the key information and meaning of the expected answer?

                Consider:
                - Similar factual content (numbers, dates, locations)
                - Similar conclusions or findings
                - Comparable level of detail and accuracy

                Respond with ONLY "1" if the insight adequately captures the expected answer, or "0" if it does not.
                """,
            )
        ]
    )

    judge_chain = JUDGE_PROMPT | HAIKU.with_structured_output(Score)

    score = judge_chain.invoke(
        {
            "expected_answer": expected_answer,
            "actual_answer": actual_answer,
        }
    )
    return score.score


def evaluate_final_answer(
    agent_state: Dict[str, Any], expected_answer: str
) -> Dict[str, Any]:
    """
    Check if final answer contains key information from expected answer using LLM-as-a-judge.

    Args:
        agent_state: Final agent state after execution
        expected_answer: Expected answer text
    Returns:
        Dict with answer_score (0 or 1), actual_answer
    """

    charts_data = agent_state.get("charts_data", [])

    if not charts_data or not expected_answer:
        return {
            "answer_score": 0,
            "actual_answer": None,
            "error": "Missing charts data or expected answer",
        }

    # Get Zeno Insight from charts data
    insight = charts_data[0].get("insight", "") if charts_data else ""

    if not insight:
        return {
            "answer_score": 0,
            "actual_answer": insight,
            "error": "No insight generated",
        }

    # LLM as judge
    score = llm_judge(expected_answer, insight)

    return {
        "answer_score": score,
        "actual_answer": insight,
        "error": "",
    }
