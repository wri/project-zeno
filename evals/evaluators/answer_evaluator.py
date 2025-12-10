"""Final answer evaluator."""

from typing import Any, Dict

from .llm_judges import llm_judge


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
    if not expected_answer:
        return {
            "answer_score": None,
            "actual_answer": None,
            "error": "Missing expected answer",
        }

    charts_data = agent_state.get("charts_data", [])

    if not charts_data or not expected_answer:
        messages = agent_state.get("messages", [])

        if messages:
            content = messages[-1].content
            # For Gemini, content is a list, with thinking and query as separate messages
            if isinstance(content, list):
                final_response = content[-1]
            else:
                final_response = content
        else:
            final_response = "Missing charts data or expected answer"
        return {
            "answer_score": 0,
            "actual_answer": None,
            "error": final_response,
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
