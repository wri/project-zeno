"""Investigator Evaluation Script

This evaluation runs against datasets created by Alyssa/Aman and uploaded via upload_dataset.py.
Results are published to LangFuse (either localhost or staging instance).
See experiments/upload_dataset.py for how to add new test data.

This evaluates high-level questions (e.g., deforestation in Amazon) with expert-verified answers.
Unlike GADM evaluation, this uses LLM-based scoring to compare non-exact matches.
"""

import asyncio
import json
import traceback
from dataclasses import dataclass
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langfuse.langchain import CallbackHandler
from langgraph.types import StateSnapshot
from typing_extensions import Annotated, Literal, TypedDict

from experiments.eval_utils import get_langfuse, get_run_name, run_query
from src.agents.agents import close_checkpointer_pool
from src.utils.database import close_global_pool, initialize_global_pool


# Global variables for REPL access
last_response = None
last_item = None


# Data structures
@dataclass
class InvestigatorAnswer:
    answer: str
    notes: Optional[str] = None


class EvaluationResult(TypedDict):
    """Evaluation result for the agent's response."""

    result: Annotated[
        Literal["pass", "fail", "unanswered"],
        ...,
        "Either 'pass', 'fail', or 'unanswered' based on evaluation",
    ]
    analysis: Annotated[str, ..., "Brief explanation of the assessment"]


# Parsing utilities
def parse_expected_output(data: dict) -> InvestigatorAnswer:
    """Convert dict to InvestigatorAnswer object."""
    return InvestigatorAnswer(
        answer=data.get("answer", ""), notes=data.get("notes")
    )


def parse_output_state_snapshot(state: StateSnapshot) -> dict:
    """Extract conversation flow from state snapshot."""
    messages = state.values.get("messages", [])
    flow = []
    step = 0

    for msg in messages:
        step += 1
        msg_type = msg.__class__.__name__

        if msg_type == "HumanMessage":
            flow.append(
                {
                    "step": step,
                    "type": "user_query_or_system_continuation",
                    "content": msg.content,
                }
            )
        elif msg_type == "AIMessage":
            # Check for tool calls
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                flow.append(
                    {
                        "step": step,
                        "type": "assistant_tool_call",
                        "tools": [
                            {
                                "name": tc["name"],
                                "arguments": tc.get("args", {}),
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
            else:
                # Extract text content
                if isinstance(msg.content, list):
                    text_parts = [
                        c.get("text", "")
                        for c in msg.content
                        if c.get("type") == "text"
                    ]
                    content = " ".join(text_parts)
                else:
                    content = str(msg.content)
                flow.append(
                    {
                        "step": step,
                        "type": "assistant_response",
                        "content": content,
                    }
                )
        elif msg_type == "ToolMessage":
            flow.append(
                {
                    "step": step,
                    "type": "tool_result",
                    "tool_name": getattr(msg, "name", "unknown"),
                    "status": getattr(msg, "status", "success"),
                    "content": getattr(msg, "content", ""),
                }
            )

    return {
        "conversation_flow": flow,
        "total_messages": len(messages),
        "final_response": _extract_final_response(messages),
    }


def _extract_final_response(messages):
    """Extract the final AI response without tool calls."""
    for msg in reversed(messages):
        if msg.__class__.__name__ == "AIMessage" and not getattr(
            msg, "tool_calls", []
        ):
            if isinstance(msg.content, list):
                text_parts = [
                    c.get("text", "")
                    for c in msg.content
                    if c.get("type") == "text"
                ]
                return " ".join(text_parts)
            else:
                return msg.content
    return None


# Scoring
def evaluate_answer(
    conversation: dict, user_query: str, golden_answer: dict, chat_model
) -> EvaluationResult:
    """Evaluate the agent's final response and reasoning.

    This evaluation checks if the agent correctly interpreted the query,
    performed necessary calculations, and produced a final answer that
    matches the golden answer. It considers the entire conversation trace.
    """
    # Create a model with structured output
    evaluator = chat_model.with_structured_output(EvaluationResult)

    prompt = f"""As an expert evaluator, your task is to assess the agent's performance in answering a user query. You must evaluate the entire process, from understanding the query to generating the final response.

**Evaluation Criteria:**

1.  **Query Interpretation:** Did the agent correctly understand the user's request?
2.  **Data Retrieval:** Did the agent access the correct dataset(s) and use appropriate parameters? (Refer to the trace for tool calls).
3.  **Analysis & Calculation:** Did the agent correctly perform any necessary calculations, data slicing, or interpretation of the retrieved data?
4.  **Reasoning:** Is the agent's reasoning sound and logical?
5.  **Final Answer:** Does the agent's final answer match the "Golden Answer"? The final answer must be factually correct and directly address the user's query.

**Instructions:**

- Review the full conversation trace, user query, and the golden answer.
- Compare the agent's `final_response` from the trace with the `answer` in the `<Golden Answer>`.
- Mark as "pass" ONLY if the agent's final answer is semantically equivalent to the golden answer and the reasoning is sound.
- Mark as "fail" if the final answer is incorrect, the reasoning is flawed, or the wrong data was used.
- Provide a brief analysis explaining your decision.

<Trace>
{json.dumps(conversation)}
</Trace>
<Query>
{user_query}
</Query>
<Golden Answer>
{json.dumps(golden_answer)}
</Golden Answer>

Now, evaluate the agent's performance and provide your assessment.
"""

    result = evaluator.invoke(prompt)
    return result


def evaluation_to_score(evaluation: EvaluationResult) -> float:
    """Convert evaluation result to numeric score."""
    if evaluation["result"] == "pass":
        return 1.0
    elif evaluation["result"] == "fail":
        return 0.0
    else:
        raise ValueError(f"Invalid result value: {evaluation['result']}")


# Main execution
async def main():
    """Main async function to run the evaluation."""
    global last_response, last_item

    await initialize_global_pool()

    try:
        langfuse = get_langfuse()
        run_name = get_run_name()
        dataset = langfuse.get_dataset("S3 T1-07 DIST & LDACS")
        chat_model = ChatAnthropic(
            model="claude-opus-4-20250514",
            max_tokens=20000,
            thinking={"type": "enabled", "budget_tokens": 10000},
        )

        # This iterates through dataset items automatically like unit tests.
        # Run locally for development, but use staging for accurate latency/cost measurements.
        # Future: Integrate with CI/CD pipeline for automated testing on code changes.
        active_items = [
            item for item in dataset.items if item.status == "ACTIVE"
        ]
        print(
            f"Evaluating {len(active_items)} active items (out of {len(dataset.items)} total)..."
        )

        handler = CallbackHandler()

        for idx, item in enumerate(active_items):
            print(f"\n{'=' * 60}")
            print(
                f"Processing item {idx + 1}/{len(active_items)}: {item.input[:50]}..."
            )

            with item.run(run_name=run_name) as root_span:
                # Execute
                print("  Calling run_query...")
                response = await run_query(
                    query=item.input,
                    handler=handler,
                    user_persona="researcher",
                    thread_id=item.id,
                )
                last_response = response
                last_item = item
                print("  run_query completed")

                # Score
                try:
                    if response is None:
                        print(
                            f"✗ Skipping item '{item.input}': response is None"
                        )
                        continue

                    print("  Parsing output...")
                    actual = parse_output_state_snapshot(response)

                    print("  Evaluating answer...")
                    evaluation = evaluate_answer(
                        actual, item.input, item.expected_output, chat_model
                    )
                    score = evaluation_to_score(evaluation)

                    # Upload
                    print("  Uploading trace...")
                    root_span.update_trace(input=item.input, output=actual)

                    root_span.score_trace(
                        name="data_interpretation_score",
                        value=score,
                        comment=f"Analysis: {evaluation['analysis']}",
                    )
                except TypeError as e:
                    # Skip this item if response is not in expected format
                    print(
                        f"✗ TypeError processing item '{item.input}': {str(e)}"
                    )
                    print(f"  Response type: {type(response)}")
                    if response:
                        print(f"  Response preview: {str(response)[:200]}...")
                    print(f"  Traceback:\n{traceback.format_exc()}")
                    continue
                finally:
                    print(f"  Flushing langfuse...")
                    langfuse.flush()

            # LLM-based scoring with analysis helps understand evaluation reasoning
            # Check LangFuse UI for detailed trace analysis of failures
            print(f"✓ {item.input} -> {score}")
            print(f"Item {idx + 1} completed")

    finally:
        # Clean up both database pool and checkpointer pool
        await close_global_pool()
        await close_checkpointer_pool()


if __name__ == "__main__":
    asyncio.run(main())
