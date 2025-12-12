"""LLM-based judge functions for evaluating agent responses."""

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from evals.utils.models import HAIKU


def llm_judge_clarification(agent_state: dict, query: str) -> dict:
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
            content = messages[-1].content
            # For Gemini, content is a list, with thinking and query as separate messages
            if isinstance(content, list):
                final_response = content[-1]
            else:
                final_response = content
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
        return result.model_dump()
    except Exception:
        return False  # Default to not clarification if LLM call fails


def llm_judge(expected_answer: str, actual_answer: str):
    """Use LLM to judge if an actual answer captures the essence of an expected answer."""

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
