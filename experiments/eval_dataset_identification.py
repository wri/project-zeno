"""Investigator Evaluation Script

This evaluation runs against datasets created by Alyssa/Aman and uploaded via upload_dataset.py.
Results are published to LangFuse (either localhost or staging instance).
See experiments/upload_dataset.py for how to add new test data.

This evaluates high-level questions (e.g., deforestation in Amazon) with expert-verified answers.
Unlike GADM evaluation, this uses LLM-based scoring to compare non-exact matches.
"""

import asyncio
import argparse
import code
import json
import sys
import traceback
from dataclasses import dataclass
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langfuse.langchain import CallbackHandler
from langgraph.types import StateSnapshot
from typing_extensions import Annotated, Literal, TypedDict

from experiments.eval_utils import get_langfuse, get_run_name, run_query


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
    """Evaluate if the agent accessed the correct dataset.

    This evaluation focuses exclusively on whether the agent's conversation trace
    shows a tool call to the dataset specified in the golden answer. It does not
    evaluate parameter correctness or the final response accuracy.
    """
    # Create a model with structured output
    evaluator = chat_model.with_structured_output(EvaluationResult)

    prompt = f"""As an expert evaluator, your task is to determine if the agent accessed the correct dataset to answer the user's query.

Your evaluation must be STRICT:
- The agent's trace MUST contain at least one tool call to the dataset specified in the "Golden Answer".
- The name of the tool called by the agent must match the expected dataset.
- You do NOT need to evaluate the correctness of tool call parameters or the final answer.

<Trace>
{json.dumps(conversation)}
</Trace>
<Query>
{user_query}
</Query>
<Golden Answer>
{json.dumps(golden_answer)}
</Golden Answer>

Review the "assistant_tool_call" events in the trace.
Mark as "pass" if any tool call matches the dataset in the golden answer. Otherwise, mark as "fail".
Provide a brief analysis explaining which tool was expected and what was found in the trace.
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


def main(dataset_name: str):
    langfuse = get_langfuse()
    run_name = get_run_name()
    dataset = langfuse.get_dataset(dataset_name)
    chat_model = ChatAnthropic(
        model="claude-opus-4-20250514",
        max_tokens=20000,
        thinking={"type": "enabled", "budget_tokens": 10000},
    )

    # This iterates through dataset items automatically like unit tests.
    # Run locally for development, but use staging for accurate latency/cost measurements.
    # Future: Integrate with CI/CD pipeline for automated testing on code changes.
    active_items = [item for item in dataset.items if item.status == "ACTIVE"]
    print(
        f"Evaluating {len(active_items)} active items (out of {len(dataset.items)} total)..."
    )

    handler = CallbackHandler()

    for item in active_items:
        with item.run(run_name=run_name) as root_span:
            # Execute
            response = asyncio.run(
                run_query(
                    query=item.input,
                    handler=handler,
                    user_persona="researcher",
                    thread_id=item.id,
                )
            )
            # Score
            try:
                actual = parse_output_state_snapshot(response)
                evaluation = evaluate_answer(
                    actual, item.input, item.expected_output, chat_model
                )
                score = evaluation_to_score(evaluation)

                # Upload
                root_span.update_trace(input=item.input, output=actual)

                root_span.score_trace(
                    name="dataset_identification_score",
                    value=score,
                    comment=f"Analysis: {evaluation['analysis']}",
                )
            except TypeError as e:
                # Skip this item if response is not in expected format
                print(f"✗ TypeError processing item '{item.input}': {str(e)}")
                print(f"  Response type: {type(response)}")
                if response:
                    print(f"  Response preview: {str(response)[:200]}...")
                print(f"  Traceback:\n{traceback.format_exc()}")
                continue
            finally:
                langfuse.flush()

        # LLM-based scoring with analysis helps understand evaluation reasoning
        # Check LangFuse UI for detailed trace analysis of failures
        print(f"✓ {item.input} -> {score}")

    if hasattr(sys, "flags") and sys.flags.interactive:
        print(
            "\nEvaluation complete. Starting interactive console to inspect variables (e.g., 'item', 'response', 'evaluation')."
        )
        code.interact(local=locals())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run dataset identification evaluation."
    )
    parser.add_argument(
        "dataset_name",
        type=str,
        nargs="?",
        default="S2 T1-02 TCL",
        help="The name of the dataset to evaluate. Defaults to 'S2 T1-02 TCL'.",
    )
    args = parser.parse_args()
    main(args.dataset_name)
