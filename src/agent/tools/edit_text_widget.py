"""edit_text_widget — replace the markdown of an existing text widget.

The companion to add_text_widget. When no widget_id is given the tool
targets the resolved dashboard's only text widget; with several text
widgets it refuses and lists the candidates (id + excerpt) so the model
can retry with an explicit id. With a widget_id the ownership check runs
against the widget's own dashboard, so a widget on someone else's
dashboard reads the same as a missing one. Owner-only, like the other
dashboard primitives.
"""

from typing import Annotated, Dict, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.add_text_widget import (
    EMPTY_TEXT_MESSAGE,
    _normalize_text,
    _widget_config,
)
from src.agent.tools.common import (
    dashboard_updated_command,
    error_command,
    load_editable_dashboard,
    resolve_dashboard_id,
)
from src.api.repositories import dashboard_writer
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_EXCERPT_CHARS = 60


def _excerpt(text: str, max_chars: int = _EXCERPT_CHARS) -> str:
    """A short single-purpose preview of a widget's markdown body."""
    text = (text or "").strip()
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def _select_text_widget(widgets) -> tuple[Optional[object], Optional[str]]:
    """The dashboard's single text widget, or an error message explaining
    why one cannot be chosen (none exist, or several do — listing each
    candidate's id and an excerpt so the model can retry with widget_id).
    """
    text_widgets = [w for w in widgets if w.widget_type == "text"]
    if not text_widgets:
        return None, (
            "No text widget on this dashboard. Add one with "
            "add_text_widget instead."
        )
    if len(text_widgets) > 1:
        listing = "; ".join(
            f'{w.id}: "{_excerpt((w.config or {}).get("text", ""))}"'
            for w in text_widgets
        )
        return None, (
            "Multiple text widgets on this dashboard — pass widget_id to "
            f"pick one. Candidates: {listing}"
        )
    return text_widgets[0], None


async def _resolve_by_widget_id(widget_id: str):
    """The (widget, dashboard) pair for an explicit widget_id, or an error
    message. Widgets on dashboards the user cannot edit, non-text widgets
    and unknown/malformed ids all resolve to an error."""
    widget = await dashboard_writer.get_widget(widget_id)
    if widget is None:
        return None, None, f"Widget {widget_id} not found."
    if widget.widget_type != "text":
        return (
            None,
            None,
            (
                f"Widget {widget_id} is a {widget.widget_type} widget, not a "
                "text widget."
            ),
        )
    dashboard = await load_editable_dashboard(
        widget.dashboard_id, "edit_text_widget"
    )
    if dashboard is None:
        return (
            None,
            None,
            (
                f"Widget {widget_id} not found or its dashboard is not "
                "editable."
            ),
        )
    return widget, dashboard, None


async def _resolve_by_dashboard(state: dict, dashboard_id: Optional[str]):
    """The (widget, dashboard) pair for the resolved dashboard's only text
    widget, or an error message."""
    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return (
            None,
            None,
            ("No dashboard to edit. Pass a dashboard_id or a widget_id."),
        )
    dashboard = await load_editable_dashboard(
        target_dashboard, "edit_text_widget"
    )
    if dashboard is None:
        return (
            None,
            None,
            (f"Dashboard {target_dashboard} not found or not editable."),
        )
    widget, message = _select_text_widget(dashboard.widgets)
    if widget is None:
        return None, None, message
    return widget, dashboard, None


@tool("edit_text_widget")
async def edit_text_widget(
    text: str,
    widget_id: Optional[str] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Replace the markdown body of an existing text widget.

    `text` is the full new markdown body (a replacement, not an append).
    `widget_id` defaults to the dashboard's only text widget — when the
    dashboard has several, the error lists their ids so you can retry with
    one. `dashboard_id` defaults to the dashboard in state or the one the
    user is currently viewing. Only dashboards the user owns can be edited.
    """
    state = state or {}

    body = _normalize_text(text)
    if body is None:
        return error_command(EMPTY_TEXT_MESSAGE, tool_call_id)

    if widget_id:
        widget, dashboard, message = await _resolve_by_widget_id(widget_id)
    else:
        widget, dashboard, message = await _resolve_by_dashboard(
            state, dashboard_id
        )
    if widget is None:
        return error_command(message, tool_call_id)

    logger.info(
        "edit_text_widget tool called",
        widget_id=str(widget.id),
        dashboard_id=str(dashboard.id),
        text_chars=len(body),
    )

    updated = await dashboard_writer.update_widget(
        widget.id, config=_widget_config(body)
    )
    if not updated:
        return error_command(
            f"Widget {widget.id} disappeared before it could be edited.",
            tool_call_id,
        )

    return dashboard_updated_command(
        dashboard.id,
        (
            f"Updated text widget {widget.id} on dashboard "
            f"'{dashboard.name}' ({dashboard.id})."
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=edit_text_widget,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- edit_text_widget(text, widget_id?, dashboard_id?): replace the "
        "markdown of an existing text widget with `text` (full "
        "replacement). Defaults to the dashboard's only text widget; when "
        "several exist the error lists their ids — retry with widget_id. "
        "Use when the user asks to change, rewrite or update a note on "
        "their dashboard."
    ),
)
