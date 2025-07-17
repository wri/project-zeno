"""Investigator Evaluation Script

This evaluation runs against datasets created by Alyssa/Aman and uploaded via upload_dataset.py.
Results are published to LangFuse (either localhost or staging instance).
See experiments/upload_dataset.py for how to add new test data.

This evaluates high-level questions (e.g., deforestation in Amazon) with expert-verified answers.
Unlike GADM evaluation, this uses LLM-based scoring to compare non-exact matches.
"""

import json
import traceback
from dataclasses import dataclass
from typing import Optional

from langgraph.types import StateSnapshot
from langchain_anthropic import ChatAnthropic
from langfuse.langchain import CallbackHandler
from typing_extensions import Annotated, TypedDict

from experiments.eval_utils import get_langfuse, get_run_name, run_query


# Data structures
@dataclass
class InvestigatorAnswer:
    answer: str
    notes: Optional[str] = None


class EvaluationResult(TypedDict):
    """Evaluation result for the agent's response."""

    pass_fail: Annotated[
        str, ..., "Either 'pass' or 'fail' based on evaluation"
    ]
    analysis: Annotated[str, ..., "Brief explanation of the assessment"]


# Parsing utilities
def parse_expected_output(data: dict) -> InvestigatorAnswer:
    """Convert dict to InvestigatorAnswer object."""
    return InvestigatorAnswer(
        answer=data.get("answer", ""), notes=data.get("notes")
    )


def parse_output_state_snapshot(state: StateSnapshot) -> dict:
    """Parse the output trace to extract messages content.

    Note: The Zeno agent dynamically decides which tools to use based on the question.
    Trace data contains all intermediate steps in JSON format - we extract only
    the relevant messages here. Use LangFuse UI to view full traces graphically.

    For debugging: LLMs can help identify patterns in complex trace data if the
    structure changes.

    Mimics: jq 'walk(if type == "object" then del(.artifact) else . end)' json_str |
            jq '{messages: .messages | map({type, content} + (if .tool_calls then {tool_calls: .tool_calls | map({name, args})} else {} end))}'
    """
    # Collect all messages from the nested structure
    messages = []
    for item in state:
        # Get messages from whichever key exists (tools or agent)
        node = item.get("tools", item.get("agent", {}))
        for message in node.get("messages", []):
            msg_data = message.get("kwargs", message)

            processed_msg = {
                "type": msg_data.get("type"),
                "content": msg_data.get("content"),
                "name": msg_data.get("name"),
            }

            # Add tool_calls if present
            if "tool_calls" in msg_data:
                processed_msg["tool_calls"] = [
                    {"name": tc["name"], "args": tc["args"]}
                    for tc in msg_data["tool_calls"]
                ]

            messages.append(processed_msg)

    return {"messages": messages}


# Scoring
def evaluate_answer(
    trace: dict, user_query: str, golden_answer: dict, chat_model
) -> EvaluationResult:
    """Evaluate answer matches using structured output.

    Uses LLM evaluation for non-exact matches. Dataset is designed with disparate
    answers to make it easier for LLMs to identify correct responses.
    TODO: Consider adding partial scoring based on retrieval quality as discussed.
    """

    # Check for empty trace (likely from error handling)
    if not trace.get("messages"):
        return EvaluationResult(
            pass_fail="fail",
            analysis="Empty response received - likely due to GraphRecursionError or other runtime error. Check run logs for details.",
        )

    # Create a model with structured output
    evaluator = chat_model.with_structured_output(EvaluationResult)

    prompt = f"""Analyze the provided agentic system trace against the user query and golden answer.
    Determine if the system responded reasonably well to the query with respect to the expected
    answer.

    <Trace>
    {json.dumps(trace)}
    </Trace>

    <Query>
    {user_query}
    </Query>

    <Golden Answer>
    {json.dumps(golden_answer)}
    </Golden Answer>

    Evaluate whether the system:
    1. Made meaningful progress toward answering the query
    2. Retrieved relevant data or information
    3. Provided the correct answer
    4. Handled errors reasonably

    Respond with pass_fail as "pass" if the system adequately addressed the query, "fail" if it did not.
    Include a brief analysis explaining your assessment."""

    result = evaluator.invoke(prompt)
    return result


def evaluation_to_score(evaluation: EvaluationResult) -> float:
    """Convert evaluation result to numeric score."""
    return 1.0 if evaluation["pass_fail"] == "pass" else 0.0


# Main execution
langfuse = get_langfuse()
run_name = get_run_name()
dataset = langfuse.get_dataset("s5_t2_02_investigator")
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

for item in active_items[:1]:
    with item.run(run_name=run_name) as root_span:
        # Execute
        response = run_query(item.input, handler, "researcher", item.id)

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
                trace_id=handler.get_trace_id(),
                name="tree_cover_answer_score",
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
