"""Dataset selection evaluator."""

import json
from typing import Any

from goldset.evaluators.utils import normalize_value


def _normalize_dataset_parameters(value: Any) -> str:
    """Normalise dataset parameters for stable JSON comparison.

    Only the `name` and `values` fields are considered for matching.
    """
    if value is None or value == "None" or str(value).strip() == "":
        return ""

    parsed_value = value
    if isinstance(value, str):
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            return normalize_value(value)

    if isinstance(parsed_value, list):
        parsed_value = [
            {"name": item.get("name"), "values": item.get("values")}
            if isinstance(item, dict)
            else item
            for item in parsed_value
        ]
    elif isinstance(parsed_value, dict):
        parsed_value = {
            "name": parsed_value.get("name"),
            "values": parsed_value.get("values"),
        }

    return json.dumps(parsed_value, sort_keys=True, separators=(",", ":"))


def evaluate_dataset_selection(
    agent_state: dict[str, Any],
    expected_dataset_id: Any,
    expected_dataset_parameters: Any,
    expected_context_layer: Any,
    query: str = "",
) -> dict[str, Any]:
    """Check if the correct dataset was selected.

    Clarification detection is handled separately by evaluate_clarification().
    This function only evaluates dataset selection.

    Args:
        agent_state: Final agent state after execution
        expected_dataset_id: Expected dataset id as string
        expected_dataset_parameters: Expected dataset parameters as JSON string
        expected_context_layer: Expected context layer as string
        query: Original user query (kept for compatibility but not used)

    Returns:
        Dict with dataset_id_match_score (0/1/None), context_layer_match_score
        (0/1/None), dataset_parameter_match_score (0/1/None),
        actual_dataset_id, actual_dataset_name, actual_dataset_parameters,
        actual_context_layer

    """
    # Actual values are extracted unconditionally (like the AOI evaluator):
    # multi-turn delta snapshots and triage need them even on turns with no
    # dataset expectation. Scores stay gated on the expectation.
    if not expected_dataset_id:
        dataset = agent_state.get("dataset") or {}
        return {
            "dataset_id_match_score": None,
            "dataset_parameter_match_score": None,
            "context_layer_match_score": None,
            "actual_dataset_id": normalize_value(dataset.get("dataset_id")) or None,
            "actual_dataset_name": dataset.get("dataset_name"),
            "actual_dataset_parameters": (
                _normalize_dataset_parameters(dataset.get("parameters")) or None
            ),
            "actual_context_layer": dataset.get("context_layer"),
        }

    dataset = agent_state.get("dataset")

    if not dataset:
        return {
            "dataset_id_match_score": 0.0,
            "dataset_parameter_match_score": None,
            "context_layer_match_score": None,
            "actual_dataset_id": None,
            "actual_dataset_name": None,
            "actual_dataset_parameters": None,
            "actual_context_layer": None,
        }

    actual_dataset_id = str(dataset.get("dataset_id", ""))
    actual_dataset_name = dataset.get("dataset_name", "")
    actual_dataset_parameters = json.dumps(
        dataset.get("parameters", []),
        separators=(",", ":"),
    )
    actual_context_layer = dataset.get("context_layer", "")

    # The expected id accepts ;-separated alternatives for cases where more than
    # one dataset is defensible (for example "8;10"); any alternative matches.
    expected_id_alternatives = {
        normalize_value(alt)
        for alt in str(expected_dataset_id).split(";")
        if normalize_value(alt)
    }
    actual_id_str = normalize_value(actual_dataset_id)
    dataset_match = actual_id_str in expected_id_alternatives

    expected_parameters_str = _normalize_dataset_parameters(expected_dataset_parameters)
    actual_parameters_str = _normalize_dataset_parameters(actual_dataset_parameters)

    expected_context_str = normalize_value(expected_context_layer)
    actual_context_str = normalize_value(actual_context_layer)

    dataset_id_match_score = 1.0 if dataset_match else 0.0

    if not expected_parameters_str:
        dataset_parameter_match_score = None
    else:
        dataset_parameter_match_score = (
            1.0 if expected_parameters_str == actual_parameters_str else 0.0
        )

    # An expected "no_selection" means the agent should choose no context layer.
    if not expected_context_str:
        context_layer_match_score = None
    elif expected_context_str == "no_selection":
        context_layer_match_score = 1.0 if not actual_context_str else 0.0
    else:
        context_layer_match = expected_context_str == actual_context_str
        context_layer_match_score = 1.0 if context_layer_match else 0.0

    return {
        "dataset_id_match_score": dataset_id_match_score,
        "dataset_parameter_match_score": dataset_parameter_match_score,
        "context_layer_match_score": context_layer_match_score,
        "actual_dataset_id": actual_dataset_id,
        "actual_dataset_name": actual_dataset_name,
        "actual_dataset_parameters": actual_dataset_parameters,
        "actual_context_layer": actual_context_layer,
    }
