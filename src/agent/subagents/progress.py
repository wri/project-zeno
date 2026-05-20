"""Progress streaming for subagents.

Subagents (geocoder, dataset selector) run several internal steps. They emit
lightweight `progress` events through LangGraph's stream_writer so a CLI or
frontend can show the flow while the tool runs.

Event shape: {"type": "progress", "subagent": str, "stage": str, "message": str}
"""

from langgraph.config import get_stream_writer


def emit_progress(subagent: str, stage: str, message: str) -> None:
    """Emit a `progress` custom event for a subagent step.

    Skips silently when called outside a streaming run — get_stream_writer
    raises RuntimeError with no runnable context and KeyError when a tool
    runs outside a LangGraph graph (e.g. a subagent exercised in a unit test).
    """
    try:
        writer = get_stream_writer()
    except (RuntimeError, KeyError):
        return
    writer(
        {
            "type": "progress",
            "subagent": subagent,
            "stage": stage,
            "message": message,
        }
    )
