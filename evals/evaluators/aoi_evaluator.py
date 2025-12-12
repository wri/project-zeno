"""AOI (Area of Interest) selection evaluator."""

from typing import Any, Dict, List, Optional

from evals.evaluators.llm_judges import llm_judge_clarification
from evals.evaluators.utils import normalize_gadm_id, normalize_value


def evaluate_aoi_selection(
    agent_state: Dict[str, Any],
    expected_aoi_ids: List[str],
    expected_subregion: Optional[str],
    query: str = "",
) -> Dict[str, Any]:
    """
    Check if the correct AOI was selected, or if agent appropriately asked for clarification.

    Args:
        agent_state: Final agent state after execution
        expected_aoi_ids: Expected AOI IDs (e.g., ["BRA", "USA.5_1"])
        expected_subregion: Expected subregion (e.g., "state-province", "country")
        query: Original user query for clarification detection
    Returns:
        Dict with aoi_score (0 or 1), actual_id, actual_name, actual_subtype, actual_source, actual_subregion
    """
    if not expected_aoi_ids:
        return {
            "aoi_score": None,
            "actual_id": None,
            "actual_name": None,
            "actual_subtype": None,
            "actual_source": None,
            "actual_subregion": None,
            "match_aoi_id": False,
            "match_subregion": False,
        }

    aoi = agent_state.get("aoi")
    subregion = agent_state.get("subregion")

    # Check if agent asked for clarification instead of selecting AOI
    if not aoi and query:
        clarification = llm_judge_clarification(agent_state, query)
        if clarification["is_clarification"]:
            # Agent appropriately asked for clarification - this is a pass
            return {
                "aoi_score": 1.0,  # Full score for appropriate clarification
                "actual_id": f"CLARIFICATION_REQUEST: {clarification['explanation']}",
                "actual_name": "Agent requested clarification",
                "actual_subtype": "clarification",
                "actual_source": "agent",
                "actual_subregion": "N/A",
                "match_aoi_id": True,  # Treat clarification as correct behavior
                "match_subregion": True,
            }

    if not aoi or not expected_aoi_ids:
        return {
            "aoi_score": None,
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
        normalized_expected = [
            normalize_gadm_id(expected_aoi_id)
            for expected_aoi_id in expected_aoi_ids
        ]
    else:
        normalized_actual = actual_aoi_id.lower()
        normalized_expected = [
            expected_aoi_id.lower() for expected_aoi_id in expected_aoi_ids
        ]

    match_aoi_id = normalized_actual in normalized_expected

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
