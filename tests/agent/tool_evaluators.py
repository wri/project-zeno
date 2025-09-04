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


def normalize_value(value) -> str:
    """Normalize values for comparison, handling None, empty strings, and 'None' strings."""
    if value is None or value == "None" or str(value).strip() == "":
        return ""
    return str(value).strip()


def evaluate_aoi_selection(
    agent_state: Dict[str, Any],
    expected_aoi_id: str,
    expected_subregion: Optional[str],
    query: str = "",
) -> Dict[str, Any]:
    """
    Check if the correct AOI was selected, or if agent appropriately asked for clarification.

    Args:
        agent_state: Final agent state after execution
        expected_aoi_id: Expected AOI ID (e.g., "BRA", "USA.5_1")
        expected_subregion: Expected subregion (e.g., "state-province", "country")
        query: Original user query for clarification detection
    Returns:
        Dict with aoi_score (0 or 1), actual_id, actual_name, actual_subtype, actual_source, actual_subregion
    """
    aoi = agent_state.get("aoi")
    subregion = agent_state.get("subregion")

    # Check if agent asked for clarification instead of selecting AOI
    if not aoi and query:
        is_clarification = llm_judge_clarification(agent_state, query)
        if is_clarification:
            # Agent appropriately asked for clarification - this is a pass
            return {
                "aoi_score": 1.0,  # Full score for appropriate clarification
                "actual_id": "CLARIFICATION_REQUEST",
                "actual_name": "Agent requested clarification",
                "actual_subtype": "clarification",
                "actual_source": "agent",
                "actual_subregion": "N/A",
                "match_aoi_id": True,  # Treat clarification as correct behavior
                "match_subregion": True,
            }

    if not aoi or not expected_aoi_id:
        return {
            "aoi_score": 0,
            "actual_id": None,
            "actual_name": None,
            "actual_subtype": None,
            "actual_source": None,
            "actual_subregion": None,
            "match_aoi_id": False,
            "match_subregion": False,
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

    # Normalize subregion values for comparison
    expected_subregion_str = normalize_value(expected_subregion)
    actual_subregion_str = normalize_value(subregion)

    # Additive scoring: AOI match = 0.75, subregion match = 0.25
    aoi_score = 0.75 if match_aoi_id else 0

    # If expected subregion is empty, treat as positive match (0.25)
    if not expected_subregion_str:
        match_subregion = True
        subregion_score = 0.25
    else:
        match_subregion = expected_subregion_str == actual_subregion_str
        subregion_score = 0.25 if match_subregion else 0

    score = aoi_score + subregion_score

    return {
        "aoi_score": score,
        "actual_id": actual_aoi_id,
        "actual_name": actual_aoi_name,
        "actual_subtype": actual_aoi_subtype,
        "actual_source": actual_aoi_source,
        "actual_subregion": actual_subregion_str,
        "match_aoi_id": match_aoi_id,
        "match_subregion": match_subregion,
    }


def evaluate_dataset_selection(
    agent_state: Dict[str, Any],
    expected_dataset_id: Any,
    expected_context_layer: Any,
    query: str = "",
) -> Dict[str, Any]:
    """
    Check if the correct dataset was selected, or if the agent asked for clarification.

    Args:
        agent_state: Final agent state after execution
        expected_dataset_id: Expected dataset id as string
        expected_context_layer: Expected context layer as string
        query: Original user query for clarification detection

    Returns:
        Dict with dataset_score (0 or 1), actual_dataset_id, actual_dataset_name, actual_context_layer
    """
    dataset = agent_state.get("dataset")

    # Check if agent asked for clarification instead of selecting a dataset
    if not dataset and query:
        is_clarification = llm_judge_clarification(agent_state, query)
        if is_clarification:
            return {
                "dataset_score": 1.0,  # Full score for appropriate clarification
                "actual_dataset_id": "CLARIFICATION_REQUEST",
                "actual_dataset_name": "Agent requested clarification",
                "actual_context_layer": "N/A",
                "error": "",
            }

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

    # Normalize values for comparison
    expected_id_str = normalize_value(expected_dataset_id)
    actual_id_str = normalize_value(actual_dataset_id)
    dataset_match = expected_id_str == actual_id_str

    expected_context_str = normalize_value(expected_context_layer)
    actual_context_str = normalize_value(actual_context_layer)

    # Additive scoring: dataset match = 0.75, context layer match = 0.25
    dataset_score = 0.75 if dataset_match else 0

    # Context layer matching: if expected is empty, treat as positive match (0.25)
    if not expected_context_str:
        context_layer_match = True
        context_score = 0.25
    else:
        context_layer_match = expected_context_str == actual_context_str
        context_score = 0.25 if context_layer_match else 0

    score = dataset_score + context_score

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
        is_clarification = llm_judge_clarification(agent_state, query)
        if is_clarification:
            return {
                "pull_data_score": 1.0,
                "row_count": 0,
                "min_rows": min_rows,
                "data_pull_success": True,  # Treat clarification as success
                "date_success": True,
                "actual_start_date": "CLARIFICATION_REQUEST",
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


def llm_judge_clarification(agent_state: Dict[str, Any], query: str) -> bool:
    """Use LLM to judge if the agent is asking for clarification instead of selecting an AOI."""

    class ClarificationJudgment(BaseModel):
        is_clarification: bool
        explanation: str

    # Get the final answer/response from the agent
    charts_data = agent_state.get("charts_data", [])
    final_response = ""

    if charts_data:
        final_response = charts_data[0].get("insight", "")

    # If no charts data, check if there's any response in the state
    if not final_response:
        messages = agent_state.get("messages", [])
        if messages:
            final_response = messages[-1].content
        else:
            final_response = ""

    if not final_response:
        return False  # No response to evaluate

    CLARIFICATION_JUDGE_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """
            You are evaluating whether an AI agent is asking for clarification instead of completing a task.

            ORIGINAL QUERY: {query}

            AGENT RESPONSE: {response}

            Does the agent response indicate that it's asking for clarification, more information, or unable to proceed due to ambiguity in the original query?

            Signs of clarification requests:
            - Asking questions back to the user
            - Requesting more specific information
            - Indicating multiple possible interpretations
            - Asking to choose between options
            - Expressing uncertainty about what the user wants

            Return true if this is a clarification request, false if the agent attempted to complete the task.
            """,
            )
        ]
    )

    judge_chain = CLARIFICATION_JUDGE_PROMPT | HAIKU.with_structured_output(
        ClarificationJudgment
    )

    try:
        result = judge_chain.invoke(
            {"query": query, "response": final_response}
        )
        return result.is_clarification
    except Exception:
        return False  # Default to not clarification if LLM call fails


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
