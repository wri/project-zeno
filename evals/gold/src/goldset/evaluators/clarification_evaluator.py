"""Centralised clarification detection evaluator."""

from typing import Any

from goldset.evaluators.llm_judges import JudgeError, llm_judge_clarification


def evaluate_clarification(
    agent_state: dict[str, Any],
    expected_clarification: bool | None,
    query: str,
) -> dict[str, Any]:
    """Detect if agent requested clarification and score it.

    This is the centralised clarification check, called once per evaluation
    before other evaluators run.

    Args:
        agent_state: Final agent state after execution
        expected_clarification: Expected clarification behaviour
            - True: clarification is expected
            - False: clarification is not expected
            - None: no expectation (the case sets no clarification value)
        query: Original user query for clarification detection

    Returns:
        Dict with:
        - actual_clarification_requested (bool): Whether agent requested clarification
        - clarification_requested_score (float | None): Score based on expectation match
        - clarification_explanation (str): Explanation from LLM judge

    Scoring logic:
        expected=True,  actual=True  → 1.0 (correct)
        expected=True,  actual=False → 0.0 (wrong: expected but not given)
        expected=False, actual=True  → 0.0 (wrong: not expected but given)
        expected=False, actual=False → 1.0 (correct)
        expected=None,  actual=True  → None (not evaluated)
        expected=None,  actual=False → None (not evaluated)

    """
    # No expectation: skip evaluation entirely (e.g. dashboard eval rows).
    if expected_clarification is None:
        return {
            "actual_clarification_requested": None,
            "clarification_requested_score": None,
            "clarification_explanation": None,
        }

    if not query:
        actual_clarification = False
        explanation = "No query provided"
    else:
        try:
            clarification = llm_judge_clarification(agent_state, query)
        except JudgeError as error:
            return {
                "actual_clarification_requested": None,
                "clarification_requested_score": None,
                "clarification_explanation": f"JUDGE ERROR: {error}",
                "judge_errors": ["clarification_requested"],
            }
        actual_clarification = clarification["is_clarification"]
        explanation = clarification["explanation"]

    if actual_clarification == expected_clarification:
        score = 1.0
    else:
        score = 0.0

    return {
        "actual_clarification_requested": actual_clarification,
        "clarification_requested_score": score,
        "clarification_explanation": explanation,
    }
