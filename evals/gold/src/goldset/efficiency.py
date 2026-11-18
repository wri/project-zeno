"""Per-case efficiency metrics: info-only, never scored.

Each trial records how much work the agent did to answer: orchestrator model
calls, tool calls, the length of the final answer and, when the thread state
carries them, the orchestrator's input and output tokens. The numbers sit in
a ledger entry's ``efficiency`` object, next to ``latency_s``.

Rules:

- These fields never change a verdict, a bucket, a check, a uid or the
  caseset_version. Nothing in ``buckets.py`` reads them.
- A metric that cannot be measured is ``None``, never ``0``.
- Tokens come from ``usage_metadata`` on the orchestrator's AI messages in the
  thread state. Model calls made inside tools (subagents, the code executor)
  never appear in the thread state, so they are not counted here. The
  Langfuse trace behind ``trace_url`` has them.
"""

from __future__ import annotations

from typing import Any

METRICS = (
    "model_calls",
    "tool_calls",
    "answer_words",
    "answer_chars",
    "input_tokens",
    "output_tokens",
)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part if isinstance(part, str) else str(part.get("text", ""))
            for part in content
            if isinstance(part, (str, dict))
        )
    return ""


def turn_messages(messages: list[Any], query: str | None) -> list[Any]:
    """The messages of the latest turn.

    The thread state holds every turn of the conversation, so a later turn of
    a multi-turn case must not count the earlier turns again. The latest turn
    starts at the last human message whose text is the turn's query. If none
    matches, it starts at the last human message. If there is no human
    message, the whole list is used.
    """
    human = [i for i, m in enumerate(messages) if getattr(m, "type", None) == "human"]
    if not human:
        return list(messages)
    start = human[-1]
    if query is not None:
        wanted = query.strip()
        for i in reversed(human):
            if _text(getattr(messages[i], "content", "")).strip() == wanted:
                start = i
                break
    return list(messages[start + 1 :])


def _final_answer(window: list[Any]) -> str | None:
    """The text of the last message, if it is an AI message."""
    if not window or getattr(window[-1], "type", None) != "ai":
        return None
    from goldset.evaluators.answer_evaluator import extract_final_answer_text

    return extract_final_answer_text(window)


def _tokens(ai_messages: list[Any]) -> tuple[int | None, int | None]:
    """Summed input and output tokens, or ``(None, None)`` when any AI
    message has no usage: a partial sum would look like a real figure."""
    if not ai_messages:
        return None, None
    total_in = total_out = 0
    for message in ai_messages:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            return None, None
        total_in += int(usage.get("input_tokens") or 0)
        total_out += int(usage.get("output_tokens") or 0)
    return total_in, total_out


def turn_efficiency(messages: list[Any], query: str | None = None) -> dict:
    """Efficiency metrics for the latest turn of a thread state."""
    window = turn_messages(messages, query)
    ai_messages = [m for m in window if getattr(m, "type", None) == "ai"]
    answer = _final_answer(window)
    input_tokens, output_tokens = _tokens(ai_messages)
    return {
        "model_calls": len(ai_messages),
        "tool_calls": sum(
            len(getattr(m, "tool_calls", None) or []) for m in ai_messages
        ),
        "answer_words": len(answer.split()) if answer is not None else None,
        "answer_chars": len(answer) if answer is not None else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def sum_efficiency(parts: list[dict | None]) -> dict | None:
    """Add per-turn metrics into one case total, as ``latency_s`` is summed.

    A metric is ``None`` when no turn measured it. A turn with no figure for a
    metric adds nothing to that metric's sum.
    """
    parts = [p for p in parts if p]
    if not parts:
        return None
    total: dict[str, int | None] = {}
    for name in METRICS:
        values = [p[name] for p in parts if p.get(name) is not None]
        total[name] = sum(values) if values else None
    return total
