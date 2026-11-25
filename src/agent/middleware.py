"""Middleware for the Zeno agent.

SessionContextMiddleware prepends a live state snapshot to every model call
so the LLM always sees the current AOI, dataset, date range, pulled data and
active insight. It reads directly from request.state (the live LangGraph
AgentState, kept up to date by tool Command(update=...) returns).

This restores harness idea #2 ("current state auto-loads every turn").
"""

from datetime import date

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
from langchain_core.messages import SystemMessage

from src.agent.datasets.curated_only import (
    CURATED_ONLY_SESSION_NOTE,
    is_curated_only,
)
from src.agent.imagery_view_status import find_imagery, imagery_result
from src.agent.language import DEFAULT_LANGUAGE, language_name
from src.agent.view_pages import get_page, on_screen_counts


def format_session_block(state: dict) -> str:
    """Render a short text block summarizing the current session state.

    Reads the current AgentState (see src/agent/state.py): aoi_selection,
    dataset, start_date/end_date, statistics, insight_id.
    """
    today = date.today().isoformat()
    lines = [f"[Session — {today}]"]

    language = state.get("language") or DEFAULT_LANGUAGE
    lines.append(
        f"Language: {language_name(language)} ({language}) — write all "
        "user-facing text (replies, insights, chart titles) in this "
        "language"
    )

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
        line = f"Dataset: {ds_name}" + (f" (context: {ctx})" if ctx else "")
        # Which of a multi-layer dataset's layers is on the map. Carried on
        # every turn, not just the one it was picked, so the agent keeps
        # narrating the layer the user is actually looking at.
        layers = dataset.get("layers") or []
        if len(layers) > 1:
            selected = dataset.get("selected_layer")
            displayed = next(
                (lyr for lyr in layers if lyr.get("name") == selected),
                layers[0],
            )
            label = displayed.get("title") or displayed.get("name")
            if label:
                line += f" (map layer: {label}"
                if displayed.get("description"):
                    line += f" — {displayed['description']}"
                line += ")"
        if is_curated_only(dataset.get("dataset_id")):
            line += f" — {CURATED_ONLY_SESSION_NOTE}"
        lines.append(line)
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
        provider = imagery.get("provider") or "sentinel-2"
        line = f"Imagery: {provider} around {imagery.get('target_date')}"
        if imagery.get("render") == "client":
            # Searched in the browser: the map reports the result in the
            # view context of each message. Absent in the turn of the
            # show_imagery call itself (the view predates it), and when the
            # user hid or removed the imagery.
            shown = find_imagery(
                state.get("view_context"), imagery.get("mosaic_id")
            )
            line += (
                f" (map: {imagery_result(shown)})"
                if shown
                else " (no map report: it comes with the next user message)"
            )
        elif imagery.get("item_count") is not None:
            line += f" ({imagery.get('item_count')} scenes)"
        lines.append(line)
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


# Tools that write no state key without a reducer. They can run in the same
# step as any other tool.
PARALLEL_SAFE_TOOLS = frozenset(
    {"read_skill", "inspect_view_context", "search_blogs"}
)


class OneStateWriterMiddleware(AgentMiddleware):
    """Keep at most one state-writing tool call in each model step.

    Most tools return a Command that writes state keys with no reducer
    (`nudge`, `dashboard_id`, `insight`, ...). When the model calls two of
    them in one step, LangGraph stops the run with
    INVALID_CONCURRENT_GRAPH_UPDATE (seen with `pick_aoi` and
    `pick_dataset`). The prompt already says to call tools one at a time;
    this makes it a guarantee. The calls in PARALLEL_SAFE_TOOLS are kept,
    and so is the first other call. The model sees the result and calls the
    dropped tools again in the next step if it still needs them. The first
    call of the step is always kept, so Gemini's thought signature (on the
    first function call) stays valid.
    """

    def after_model(self, state, runtime):
        messages = state.get("messages") or []
        if not messages:
            return None
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if len(tool_calls) < 2:
            return None
        kept, writer_seen = [], False
        for call in tool_calls:
            if call["name"] in PARALLEL_SAFE_TOOLS:
                kept.append(call)
            elif not writer_seen:
                kept.append(call)
                writer_seen = True
        if len(kept) == len(tool_calls):
            return None
        return {"messages": [last.model_copy(update={"tool_calls": kept})]}
