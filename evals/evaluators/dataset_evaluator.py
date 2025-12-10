"""Dataset selection evaluator."""

from typing import Any, Dict

from .llm_judges import llm_judge_clarification
from .utils import normalize_value


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
    if not expected_dataset_id:
        return {
            "dataset_score": None,
            "actual_dataset_id": None,
            "actual_dataset_name": None,
            "actual_context_layer": None,
            "error": "Missing dataset data",
        }
    dataset = agent_state.get("dataset")

    # Check if agent asked for clarification instead of selecting a dataset
    if not dataset and query:
        clarification = llm_judge_clarification(agent_state, query)
        if clarification["is_clarification"]:
            return {
                "dataset_score": 1.0,  # Full score for appropriate clarification
                "actual_dataset_id": f"CLARIFICATION_REQUEST: {clarification['explanation']}",
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
