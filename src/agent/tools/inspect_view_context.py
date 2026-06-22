"""inspect_view_context — surface the user's current frontend view state.

The frontend sends an ambient "view state" snapshot (which page the user is
on, the map viewport, which layers and AOIs are visible) with each chat
request. It is stored on AgentState (``view_context``) but deliberately kept
out of the prompt — only a one-line breadcrumb appears in the session block.
This tool returns the full snapshot when the agent actually needs it to answer
a query that refers to what the user is looking at.
"""

import json
from typing import Annotated, Dict, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _label(item: object, *keys: str) -> str:
    """Best human-readable label for a layer/AOI entry, always a string."""
    if isinstance(item, dict):
        for key in keys:
            value = item.get(key)
            if value:
                return str(value)
        return "?"
    return str(item)


def format_view_context(view: dict) -> str:
    """Render the full frontend view-state snapshot as readable text.

    The snapshot is free-form (the frontend owns its shape); we surface the
    well-known keys explicitly and fall back to a JSON dump for the rest so
    nothing the frontend sends is silently dropped.
    """
    if not view:
        return (
            "No frontend view context is available — the app did not report "
            "what the user is currently looking at."
        )

    lines = ["Current frontend view:"]

    page = view.get("page")
    if page:
        lines.append(f"- Page: {page}")

    viewport = view.get("viewport")
    if viewport:
        bbox = viewport.get("bbox") if isinstance(viewport, dict) else None
        zoom = viewport.get("zoom") if isinstance(viewport, dict) else None
        parts = []
        if bbox:
            parts.append(f"bbox {bbox}")
        if zoom is not None:
            parts.append(f"zoom {zoom}")
        lines.append(f"- Viewport: {', '.join(parts) if parts else viewport}")

    layers = view.get("visible_layers")
    if layers:
        names = [_label(layer, "name", "id") for layer in layers]
        lines.append(f"- Visible layers ({len(names)}): {', '.join(names)}")

    aois = view.get("visible_aois")
    if aois:
        names = [_label(aoi, "name", "src_id") for aoi in aois]
        lines.append(f"- Visible AOIs ({len(names)}): {', '.join(names)}")

    # Surface any other keys the frontend sent so nothing is lost.
    known = {"page", "viewport", "visible_layers", "visible_aois"}
    extra = {k: v for k, v in view.items() if k not in known}
    if extra:
        lines.append(f"- Other: {json.dumps(extra, default=str)}")

    return "\n".join(lines)


@tool("inspect_view_context")
async def inspect_view_context(
    state: Annotated[Dict, InjectedState],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Return what the user is currently looking at in the app.

    Reports the current page (map vs report), the map viewport, and the
    layers and AOIs visible on screen. Call this when the user refers to
    "this", "here", the current view, or what's on their screen, and you need
    those details to answer.
    """
    logger.info("inspect_view_context tool called")
    view = (state or {}).get("view_context") or {}
    return Command(
        update={
            "messages": [
                ToolMessage(
                    format_view_context(view),
                    tool_call_id=tool_call_id,
                    status="success",
                )
            ],
        },
    )


SPEC = ToolSpec(
    tool=inspect_view_context,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- inspect_view_context(): returns what the user is currently looking "
        "at in the app (page, map viewport, visible layers, visible AOIs). "
        "Call this when the user refers to 'this', 'here', the current view, "
        "or what's on their screen."
    ),
)
