import json
from dataclasses import dataclass
from typing import Optional
from typing_extensions import Annotated, TypedDict
from langchain_anthropic import ChatAnthropic

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


def parse_output_trace(json_str: str) -> dict:
    """
    Parse the output trace to extract messages content.
    Mimics: jq 'walk(if type == "object" then del(.artifact) else . end)' json_str |
            jq '{messages: .messages | map({type, content} + (if .tool_calls then {tool_calls: .tool_calls | map({name, args})} else {} end))}'
    """
    data = json.loads(json_str)

    # Collect all messages from the nested structure
    messages = []
    for item in data:
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
    """Evaluate answer matches using structured output."""

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
    answer. Be lenient in your assessment.

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
    3. Provided or approached the correct answer
    4. Handled errors reasonably

    Respond with pass_fail as "pass" if the system adequately addressed the query (even partially), "fail" if it did not.
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

active_items = [item for item in dataset.items if item.status == "ACTIVE"]
print(
    f"Evaluating {len(active_items)} active items (out of {len(dataset.items)} total)..."
)

for item in active_items:
    # Execute
    handler = item.get_langchain_handler(run_name=run_name)
    response = run_query(item.input, handler, "researcher", item.id)

    # Score
    actual = parse_output_trace(response)
    evaluation = evaluate_answer(
        actual, item.input, item.expected_output, chat_model
    )
    score = evaluation_to_score(evaluation)

    # Upload
    langfuse.score(
        trace_id=handler.get_trace_id(),
        name="tree_cover_answer_score",
        value=score,
        comment=f"Analysis: {evaluation['analysis']}",
    )
    langfuse.flush()

    print(f"✓ {item.input} -> {score}")
