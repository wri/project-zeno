import base64
import json
from typing import Any

from goldset.evaluators.llm_judges import (
    llm_judge,
    llm_judge_chart,
    llm_judge_expected_text,
)


def _decode_codeact_parts(raw_parts: list[dict[str, Any]]) -> str:
    """Decode base64-encoded codeact parts into a readable summary string.

    The codeact_parts from agent state are stored with base64-encoded content.
    Parts have types: 'code_block' (Python code), 'text_output' (LLM reasoning),
    'execution_output' (printed stats/results).

    Returns a formatted string grouped by type, capped at a reasonable length.
    """
    if not raw_parts:
        return ""

    grouped: dict[str, list[str]] = {}
    for part in raw_parts:
        part_type = part.get("type", "unknown")
        content_b64 = part.get("content", "")
        try:
            decoded = base64.b64decode(content_b64).decode("utf-8")
        except Exception:
            decoded = content_b64  # fallback: use raw content

        grouped.setdefault(part_type, []).append(decoded)

    sections = []
    type_labels = {
        "code_block": "CODE",
        "text_output": "LLM REASONING",
        "execution_output": "EXECUTION OUTPUT",
    }
    for part_type, contents in grouped.items():
        label = type_labels.get(part_type, part_type.upper())
        combined = "\n---\n".join(contents)
        combined = combined[:8000]
        sections.append(f"## {label}\n\n{combined}")

    return "\n\n".join(sections)


_CHARTS_JSON_LIMIT = 80_000


def _serialize_charts_json(charts: list[dict[str, Any]]) -> str:
    """Serialise all charts (without their insight prose), always as valid JSON.

    Output over _CHARTS_JSON_LIMIT characters is never cut as a string, because
    invalid JSON would leave chart_numeric with no candidates and force a numeric
    failure. Instead it drops trailing charts, then halves data rows, and marks
    the result with "_truncated": true.
    """
    if not charts:
        return ""
    chart_jsons = []
    for chart in charts:
        cleaned = {key: value for key, value in chart.items() if key != "insight"}
        if cleaned:
            chart_jsons.append(dict(cleaned))
    if not chart_jsons:
        return ""

    def dump(items: list[dict[str, Any]]) -> str:
        return json.dumps(items, ensure_ascii=False, default=str)

    serialized = dump(chart_jsons)
    if len(serialized) <= _CHARTS_JSON_LIMIT:
        return serialized

    kept = chart_jsons
    while len(kept) > 1 and len(dump(kept)) > _CHARTS_JSON_LIMIT:
        kept = kept[:-1]
    while len(dump(kept)) > _CHARTS_JSON_LIMIT:
        shrunk = False
        for chart in kept:
            data = chart.get("data")
            if isinstance(data, list) and len(data) > 1:
                chart["data"] = data[: len(data) // 2]
                shrunk = True
        if not shrunk:
            # a single unsplittable monster; keep the metadata, drop the bulk
            kept = [{k: v for k, v in kept[0].items() if k != "data"}]
            break
    kept[0]["_truncated"] = True
    return dump(kept)


def extract_final_answer_text(messages: list[Any]) -> str:
    """Final assistant message as plain text (Claude string / Gemini list)."""
    if not messages:
        return ""
    content = messages[-1].content
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content:
        last_item = content[-1]
        if isinstance(last_item, dict) and "text" in last_item:
            return last_item["text"]
        return str(last_item)
    return str(content) if content else ""


def _score_and_reason(result: Any) -> tuple[float | None, str | None]:
    """Normalise judge responses that may be a score or score/reason mapping."""
    if isinstance(result, dict):
        return result.get("score"), result.get("reason")
    return result, None


def evaluate_final_answer(
    agent_state: dict[str, Any],
    expected_answer: str,
    expected_text: str = "",
    query: str = "",
) -> dict[str, Any]:
    """Score the agent's answer and charts against the case's expected answer and text.

    Clarification detection is handled separately by evaluate_clarification().
    This function only evaluates answers.

    Returns answer scores:
    - charts_answer_score: whether the chart data contains the expected figure
      (deterministic; see resolve_chart_verdict)
    - charts_answer_judge_score: the chart judge's own verdict, info-only
    - agent_answer_score: Compares expected_answer to messages[-1].content
    - expected_text_match_score: Checks whether messages[-1].content includes
      expected_text semantically
    - *_reason fields: Concise LLM explanations for each score

    Args:
        agent_state: Final agent state after execution
        expected_answer: Expected answer text
        expected_text: Expected text, meaning, or behaviour to check in agent response
        query: Original user query

    """
    # Extract charts data (all charts, not just the first)
    charts_data = agent_state.get("charts_data", [])
    actual_charts_answer = "; ".join(
        chart.get("insight", "") for chart in charts_data if chart.get("insight")
    )
    actual_charts_json = _serialize_charts_json(charts_data)

    actual_agent_answer = extract_final_answer_text(agent_state.get("messages", []))

    # Extract codeact parts (base64-encoded code/output from agent reasoning)
    raw_codeact_parts = agent_state.get("codeact_parts", [])
    codeact_summary = _decode_codeact_parts(raw_codeact_parts)

    judge_errors: list[str] = []

    # Score the chart JSON, not the prose insight. The score comes from the
    # deterministic comparator; the judge's own verdict is kept as
    # `charts_answer_judge`, which is info-only (buckets.INFO_ONLY) so its
    # reliability can be tracked before it is ever allowed to gate.
    charts_answer_score = None
    charts_answer_score_reason = None
    charts_answer_judge_score = None
    if expected_answer and actual_charts_json:
        try:
            verdict = llm_judge_chart(
                query,
                expected_answer,
                actual_charts_json,
                codeact_summary=codeact_summary,
                include_reason=True,
            )
            charts_answer_score, charts_answer_score_reason = _score_and_reason(verdict)
            if isinstance(verdict, dict):
                charts_answer_judge_score = verdict.get("judge_score")
        except Exception as error:  # judge outage: an error, never a verdict
            charts_answer_score_reason = f"JUDGE ERROR: {error}"
            judge_errors.append("charts_answer")

    agent_answer_score = None
    agent_answer_score_reason = None
    if expected_answer and actual_agent_answer:
        try:
            agent_answer_score, agent_answer_score_reason = _score_and_reason(
                llm_judge(
                    expected_answer,
                    actual_agent_answer,
                    include_reason=True,
                ),
            )
        except Exception as error:
            agent_answer_score_reason = f"JUDGE ERROR: {error}"
            judge_errors.append("agent_answer")

    expected_text_match_score = None
    expected_text_match_score_reason = None
    if expected_text and actual_agent_answer:
        try:
            expected_text_match_score, expected_text_match_score_reason = (
                _score_and_reason(
                    llm_judge_expected_text(
                        expected_text,
                        actual_agent_answer,
                        include_reason=True,
                    ),
                )
            )
        except Exception as error:
            expected_text_match_score_reason = f"JUDGE ERROR: {error}"
            judge_errors.append("expected_text_match")

    return {
        "charts_answer_score": charts_answer_score,
        "charts_answer_judge_score": charts_answer_judge_score,
        "chart_answer_score_reason": charts_answer_score_reason,
        "agent_answer_score": agent_answer_score,
        "agent_answer_score_reason": agent_answer_score_reason,
        "expected_text_match_score": expected_text_match_score,
        "expected_text_match_score_reason": expected_text_match_score_reason,
        "actual_charts_answer": actual_charts_answer or None,
        "actual_charts_json": actual_charts_json or None,
        "actual_agent_answer": actual_agent_answer or None,
        "actual_codeact_summary": codeact_summary or None,
        "judge_errors": judge_errors,
    }
