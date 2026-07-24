"""Middleware for the Zeno agent.

SessionContextMiddleware prepends a live state snapshot to every model call
so the LLM always sees the current AOI, dataset, date range, pulled data and
active insight. It reads directly from request.state (the live LangGraph
AgentState, kept up to date by tool Command(update=...) returns).

This restores harness idea #2 ("current state auto-loads every turn").
"""

from datetime import date

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage, ToolMessage

from src.agent.view_pages import get_page, on_screen_counts


def format_session_block(state: dict) -> str:
    """Render a short text block summarizing the current session state.

    Reads the current AgentState (see src/agent/state.py): aoi_selection,
    dataset, start_date/end_date, statistics, insight_id.
    """
    today = date.today().isoformat()
    lines = [f"[Session — {today}]"]

    aoi = state.get("aoi_selection") or {}
    name = aoi.get("name")
    aois = aoi.get("aois") or []
    if name:
        suffix = f" ({len(aois)} area(s))" if aois else ""
        lines.append(f"AOI: {name}{suffix}")
    else:
        lines.append("AOI: none")

    dataset = state.get("dataset") or {}
    ds_name = dataset.get("dataset_name")
    if ds_name:
        ctx = dataset.get("context_layer")
        lines.append(
            f"Dataset: {ds_name}" + (f" (context: {ctx})" if ctx else "")
        )
    else:
        lines.append("Dataset: none")

    start = state.get("start_date")
    end = state.get("end_date")
    lines.append(
        f"Date range: {start} → {end}" if start or end else "Date range: none"
    )

    stats = state.get("statistics") or []
    if stats:
        labels = []
        for s in stats:
            label = s.get("id") or s.get("dataset_name") or "?"
            labels.append(str(label))
        lines.append(f"Pulled data: {len(stats)} ({', '.join(labels)})")
    else:
        lines.append("Pulled data: none")

    imagery = state.get("imagery") or {}
    if imagery:
        lines.append(
            f"Imagery: Sentinel-2 around {imagery.get('target_date')} "
            f"({imagery.get('item_count')} scenes)"
        )
    else:
        lines.append("Imagery: none")

    insight_id = state.get("insight_id")
    lines.append(
        f"Active insight: {insight_id}"
        if insight_id
        else "Active insight: none"
    )

    lines.append(_view_breadcrumb(state.get("view_context")))

    return "\n".join(lines)


def _view_breadcrumb(view: dict | None) -> str:
    """One-line scope hint for the surface the user is on.

    Registered pages (src/agent/view_pages.py) render their own line with
    the page's scope semantics ("this dashboard" = ..., etc.); unregistered
    pages fall back to the generic count summary. Either way the bulky
    snapshot (exact viewport, full layer list) stays out of the prompt —
    the agent calls inspect_view_context when it actually needs it.
    """
    if not view:
        return "View: none"

    page_meta = get_page(view)
    if page_meta is not None:
        return page_meta.session_line(view)

    parts = []
    page = view.get("page")
    if page:
        parts.append(f"{page} page")
    parts.extend(on_screen_counts(view))

    summary = " · ".join(parts) if parts else "active"
    return f"View: {summary} (call inspect_view_context for details)"


class SessionContextMiddleware(AgentMiddleware):
    """Prepend a short session-context system message before every model
    call so the LLM always sees the current AOI, dataset, date range,
    pulled data and active insight.

    Reads from request.state which is the live LangGraph agent state,
    automatically updated by Command returns from tools.
    """

    async def awrap_model_call(self, request: ModelRequest, handler):
        state = request.state or {}
        block = format_session_block(state)
        request.messages = [
            SystemMessage(content=block),
            *request.messages,
        ]
        if request.runtime is not None:
            request.runtime.stream_writer(
                {
                    "type": "context",
                    "session_block": block,
                    "message_count": len(request.messages),
                }
            )
        return await handler(request)


class StopOnHumanFeedbackMiddleware(AgentMiddleware):
    """Hard-stop the ReAct loop after a tool signals it's waiting on the
    user (``response_metadata={"msg_type": "human_feedback"}`` — pick_aoi's
    and pick_dataset's clarifying questions, send_nudge's clickable
    options, etc.).

    Nothing in the standard create_agent loop enforces this: the model ->
    tools -> model edge only checks whether the last AI message made tool
    calls, never response_metadata, so the model is otherwise free to
    ignore the "stop and wait" instructions scattered across tool/skill
    prompts and chain another tool call (or answer on the user's behalf)
    in the same turn. This makes it structurally impossible instead of
    merely discouraged: whenever the most recent run of ToolMessages
    (since the last non-tool message) includes a human_feedback tag, the
    upcoming model call is stripped of its tools, so the model can only
    reply in plain text — which the existing "zero tool calls" edge then
    ends the turn on.
    """

    async def awrap_model_call(self, request: ModelRequest, handler):
        recent_tool_messages = []
        for message in reversed(request.messages):
            if not isinstance(message, ToolMessage):
                break
            recent_tool_messages.append(message)

        waiting_on_user = any(
            (message.response_metadata or {}).get("msg_type")
            == "human_feedback"
            for message in recent_tool_messages
        )
        if waiting_on_user:
            request = request.override(tools=[])
        return await handler(request)
