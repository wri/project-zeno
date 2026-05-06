from datetime import date

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
from langchain_core.messages import AIMessage, SystemMessage

from src.agent.harness.protocol import ContextEvent, MessagePreview


def _format_session_block(session) -> str:
    s = getattr(session, "state", {}) or {}
    today = date.today().isoformat()
    lines = [f"[Session — {today}]"]

    refs = s.get("aoi_refs") or []
    if refs:
        names = ", ".join(
            f"{r['name']} ({r['source']}:{r['src_id']})" for r in refs
        )
        lines.append(f"AOI: {names}")
    else:
        lines.append("AOI: none")

    dataset = s.get("dataset_id") or "none"
    lines.append(f"Dataset: {dataset}")

    data_refs = s.get("data_refs") or []
    lines.append(
        f"Data: {', '.join(data_refs) if data_refs else 'none'}"
    )

    art_ids = s.get("artifact_ids") or []
    lines.append(
        "Active artifact: "
        + (f"@{art_ids[-1]}" if art_ids else "none")
    )

    ui = getattr(session, "ui_context", None)
    if ui is not None and ui.active_artifact_id:
        lines.append(f"UI active artifact: @{ui.active_artifact_id}")

    return "\n".join(lines)


def _message_preview(msg) -> MessagePreview:
    role_raw = type(msg).__name__.replace("Message", "").lower()
    role = role_raw or "unknown"
    text = ""
    tool_calls: list[str] = []
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    parts.append(str(block.get("text", "")))
                elif btype == "thinking":
                    parts.append(
                        "[thinking] " + str(block.get("thinking", ""))[:160]
                    )
            else:
                parts.append(str(block))
        text = " ".join(p for p in parts if p)
    text = text.strip().replace("\n", " ")
    if len(text) > 240:
        text = text[:240] + "…"
    for tc in getattr(msg, "tool_calls", None) or []:
        tool_calls.append(tc.get("name", "?"))
    return MessagePreview(role=role, text=text, tool_calls=tool_calls)


class SessionContextMiddleware(AgentMiddleware):
    """Prepend a short session-context system message before every model
    call. Reads from the session held in runtime context. Also emits a
    ContextEvent so the renderer can show what the orchestrator sees on
    each turn."""

    async def awrap_model_call(self, request: ModelRequest, handler):
        session = None
        runtime = request.runtime
        if runtime is not None and isinstance(runtime.context, dict):
            session = runtime.context.get("session")
        if session is not None:
            block = _format_session_block(session)
            recent = [_message_preview(m) for m in request.messages[-3:]]
            session._events.put_nowait(
                ContextEvent(
                    system_block=block,
                    message_count=len(request.messages),
                    recent=recent,
                )
            )
            request.messages = [
                SystemMessage(content=block),
                *request.messages,
            ]
        return await handler(request)


class DatasetTrackingMiddleware(AgentMiddleware):
    """Sniff tool calls / messages for `dataset_id` references and update
    the session state. The orchestrator picks a dataset by reading
    `list_datasets` results — there is no dedicated state-mutating tool, so
    we infer it post-hoc from the recent tool messages."""

    async def aafter_model(self, state, runtime):
        session = None
        if runtime is not None and isinstance(runtime.context, dict):
            session = runtime.context.get("session")
        if session is None:
            return None

        messages = state.get("messages") or []
        for msg in reversed(messages[-6:]):
            if not isinstance(msg, AIMessage):
                continue
            for call in getattr(msg, "tool_calls", None) or []:
                args = call.get("args") or {}
                ds = args.get("dataset_id")
                if ds and session.state.get("dataset_id") != ds:
                    session.set_dataset(ds)
                    return None
        return None
