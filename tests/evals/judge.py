"""
LLM-as-judge for evaluating generate_insights output against rubrics.

Uses Haiku for fast, cheap checklist-style grading.
Every judgment logs: query, rubric, tool_output summary, judge prompt,
judge raw response, verdict, and comment.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field

from src.agent.llms import SMALL_MODEL
from src.agent.tools.generate_insights import generate_insights

logger = logging.getLogger("evals.judge")


@dataclass
class Verdict:
    """Result of a single eval judgment."""

    passed: bool
    comment: str
    requirements: list[dict] = field(default_factory=list)
    # Full trace for debugging / results JSON
    judge_prompt: str = ""
    judge_raw_response: str = ""
    tool_output_summary: dict = field(default_factory=dict)


JUDGE_PROMPT = """You are evaluating whether an AI-generated data visualization follows specific rules.

## Original User Query
{query}

## Expected Behavior (Rubric)
{rubric}

## Actual Tool Output

### Chart Type
{chart_type}

### Chart Data (first 10 rows)
{chart_data_preview}

### Insight Text
{insight_text}

### Generated Code (summary)
{generated_code}

## Instructions
Evaluate whether the actual output satisfies EACH requirement in the rubric.
For each requirement, state whether it is MET or NOT MET with a brief reason.

Then give an overall verdict: PASS if ALL requirements are met, FAIL if ANY is not met.

Respond ONLY with valid JSON in this exact format (no markdown fencing):
{{"requirements": [{{"requirement": "...", "met": true, "reason": "..."}}, ...], "verdict": "PASS", "comment": "Brief overall explanation"}}"""


async def judge_output(query: str, rubric: str, tool_output: dict) -> Verdict:
    """
    Evaluate tool output against a rubric using Haiku.

    Args:
        query: The original user query
        rubric: Expected behavior description
        tool_output: Dict with keys: chart_type, chart_data, insight, code

    Returns:
        Verdict with pass/fail, explanation, and full trace
    """
    import pandas as pd

    # Format chart data preview
    chart_data = tool_output.get("chart_data", [])
    if chart_data:
        df = pd.DataFrame(chart_data[:10])
        chart_data_preview = df.to_csv(index=False)
    else:
        chart_data_preview = "(no chart data)"

    prompt = JUDGE_PROMPT.format(
        query=query,
        rubric=rubric,
        chart_type=tool_output.get("chart_type", "(unknown)"),
        chart_data_preview=chart_data_preview,
        insight_text=tool_output.get("insight", "(no insight)"),
        generated_code=tool_output.get("code", "(no code)")[:2000],
    )

    # Build a summary of what the tool produced (for logging, not sent to judge)
    tool_summary = {
        "chart_type": tool_output.get("chart_type"),
        "chart_data_rows": len(tool_output.get("chart_data", [])),
        "chart_data_columns": list(tool_output["chart_data"][0].keys())
        if tool_output.get("chart_data")
        else [],
        "insight_preview": (tool_output.get("insight") or "")[:300],
        "refused": tool_output.get("refused", False),
    }

    response = await SMALL_MODEL.ainvoke(prompt)

    # Parse JSON from response — content may be a string or list of content blocks
    raw_content = response.content
    if isinstance(raw_content, list):
        raw_text = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        ).strip()
    else:
        raw_text = raw_content.strip()

    text = raw_text
    # Handle potential markdown fencing
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        verdict = Verdict(
            passed=False,
            comment=f"Judge returned unparseable response: {text[:200]}",
            judge_prompt=prompt,
            judge_raw_response=raw_text,
            tool_output_summary=tool_summary,
        )
        _log_verdict(query, rubric, verdict)
        return verdict

    verdict = Verdict(
        passed=result.get("verdict", "").upper() == "PASS",
        comment=result.get("comment", ""),
        requirements=result.get("requirements", []),
        judge_prompt=prompt,
        judge_raw_response=raw_text,
        tool_output_summary=tool_summary,
    )
    _log_verdict(query, rubric, verdict)
    return verdict


def _log_verdict(query: str, rubric: str, verdict: Verdict):
    """Log the full judgment chain for debugging."""
    status = "PASS ✅" if verdict.passed else "FAIL ❌"
    logger.info(
        f"\n{'='*70}\n"
        f"EVAL JUDGMENT: {status}\n"
        f"{'='*70}\n"
        f"Query: {query}\n"
        f"Rubric: {rubric.strip()}\n"
        f"Tool output: chart_type={verdict.tool_output_summary.get('chart_type')}, "
        f"rows={verdict.tool_output_summary.get('chart_data_rows')}, "
        f"cols={verdict.tool_output_summary.get('chart_data_columns')}, "
        f"refused={verdict.tool_output_summary.get('refused')}\n"
        f"Insight preview: {verdict.tool_output_summary.get('insight_preview', '')[:200]}\n"
        f"Judge comment: {verdict.comment}\n"
        f"Requirements:\n"
        + "\n".join(
            f"  {'✓' if r.get('met') else '✗'} {r.get('requirement', '?')}: {r.get('reason', '')}"
            for r in verdict.requirements
        )
        + f"\n{'='*70}"
    )


async def run_generate_insights(query: str, state: dict) -> dict:
    """
    Run generate_insights and extract the fields the judge needs.

    Returns dict with: chart_type, chart_data, insight, code, refused
    """
    tool_call_id = str(uuid.uuid4())
    command = await generate_insights.ainvoke(
        {
            "type": "tool_call",
            "name": "generate_insights",
            "id": tool_call_id,
            "args": {
                "query": query,
                "state": state,
            },
        }
    )

    update = command.update
    result = {
        "chart_type": None,
        "chart_data": [],
        "insight": "",
        "code": "",
        "refused": False,
    }

    # Check for refusal/error — tool returned error status with no chart data
    messages = update.get("messages", [])
    if messages:
        msg = messages[0]
        msg_content = msg.content if hasattr(msg, "content") else str(msg)
        msg_status = getattr(msg, "status", None)
        result["tool_message"] = msg_content
        if msg_status == "error" or (
            not update.get("charts_data") and "fail" in msg_content.lower()
        ):
            result["refused"] = True
            result["insight"] = msg_content

    charts_data = update.get("charts_data", [])
    if charts_data:
        chart = charts_data[0]
        result["chart_type"] = chart.get("type")
        result["chart_data"] = chart.get("data", [])
        result["insight"] = chart.get("insight", "")

    # Extract code from codeact_parts
    codeact_parts = update.get("codeact_parts", [])
    code_parts = []
    for part in codeact_parts:
        if isinstance(part, dict) and part.get("type") == "code_block":
            code_parts.append(part.get("content", ""))
        elif hasattr(part, "type") and str(part.type) == "code_block":
            code_parts.append(getattr(part, "content", ""))
    result["code"] = "\n".join(code_parts)

    return result
