"""Suggested datasets evaluator (a legacy field).

The agent no longer writes ``suggested_datasets``: the ``nudge`` field replaced it,
and dataset suggestions now arrive as a ``dataset_choice`` nudge. A case that sets
this expectation scores 0.0 for that reason alone. For new cases, expect
``nudge_type: dataset_choice`` or ``scope: suggest`` instead.
"""

from typing import Any


def evaluate_suggested_datasets(
    agent_state: dict[str, Any],
    expected_suggested_datasets: list[str] | None,
) -> dict[str, Any]:
    """Check if suggested datasets are a valid non-empty subset of expected.

    Args:
        agent_state: Final agent state after execution
        expected_suggested_datasets: Allowed dataset IDs. The agent must
            suggest at least one, and may not suggest any outside this set.

    Returns:
        Dict with:
        - suggested_datasets_match_score (0/1/None): 1.0 if at least one
          suggested dataset matches and all are within the expected set,
          0.0 otherwise, None if expected_suggested_datasets is not provided
        - actual_suggested_datasets (str | None): Semicolon-separated actual
          suggested datasets from agent state

    """
    # Actual values are extracted unconditionally (like the AOI and dataset
    # evaluators): multi-turn delta snapshots and triage need them even on
    # turns with no expectation. Scores stay gated on the expectation.
    actual = agent_state.get("suggested_datasets", [])
    if isinstance(actual, str):
        raw_list = [s.strip() for s in actual.split(";") if s.strip()]
    elif isinstance(actual, list):
        raw_list = [s for s in actual if s]
    else:
        raw_list = []

    # Extract dataset_id when items are dicts; otherwise use the value as-is
    def _to_id_str(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("dataset_id", "")).strip()
        return str(item).strip()

    actual_list = [_to_id_str(s) for s in raw_list if _to_id_str(s)]
    actual_str = "; ".join(actual_list) if actual_list else None

    if not expected_suggested_datasets:
        return {
            "suggested_datasets_match_score": None,
            "actual_suggested_datasets": actual_str,
        }

    if not actual_list:
        return {
            "suggested_datasets_match_score": 0.0,
            "actual_suggested_datasets": actual_str,
        }

    expected_normalized = {s.strip().lower() for s in expected_suggested_datasets}
    actual_normalized = {s.strip().lower() for s in actual_list}

    at_least_one_match = bool(actual_normalized & expected_normalized)
    all_within_expected = actual_normalized.issubset(expected_normalized)
    score = 1.0 if (at_least_one_match and all_within_expected) else 0.0

    return {
        "suggested_datasets_match_score": score,
        "actual_suggested_datasets": actual_str,
    }
