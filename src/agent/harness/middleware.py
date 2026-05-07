"""Middleware for the Zeno harness.

SessionContextMiddleware prepends a live state snapshot to every model call
so the LLM knows what AOI, dataset, data, and artifacts are active. It reads
directly from request.state (the current LangGraph agent state).
"""

from datetime import date

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage


def _format_session_block(state: dict) -> str:
    """Render a short text block summarizing the current session state."""
    today = date.today().isoformat()
    lines = [f"[Session - {today}]"]

    refs = state.get("aoi_refs") or []
    if refs:
        names = ", ".join(
            f"{r['name']} ({r['source']}:{r['src_id']})" for r in refs
        )
        lines.append(f"AOI: {names}")
    else:
        lines.append("AOI: none")

    dataset = state.get("dataset_id") or "none"
    lines.append(f"Dataset: {dataset}")

    data_refs = state.get("data_refs") or []
    lines.append(
        f"Data: {', '.join(data_refs) if data_refs else 'none'}"
    )

    art_ids = state.get("artifact_ids") or []
    lines.append(
        "Active artifact: "
        + (f"@{art_ids[-1]}" if art_ids else "none")
    )

    return "\n".join(lines)


class SessionContextMiddleware(AgentMiddleware):
    """Prepend a short session-context system message before every model
    call so the LLM always sees the current AOI, dataset, data refs, and
    active artifact.

    Reads from request.state which is the live LangGraph agent state,
    automatically updated by Command returns from tools.
    """

    async def awrap_model_call(self, request: ModelRequest, handler):
        state = request.state or {}
        block = _format_session_block(state)
        request.messages = [
            SystemMessage(content=block),
            *request.messages,
        ]
        if request.runtime is not None:
            request.runtime.stream_writer({
                "type": "context",
                "session_block": block,
                "message_count": len(request.messages),
            })
        return await handler(request)
