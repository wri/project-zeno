"""add_text_widget — put a composed markdown note onto a dashboard.

The fourth dashboard primitive next to create_dashboard, add_to_dashboard
and add_map_widget. The agent composes the markdown itself (a summary of
findings, a section intro, a caveat) and it lands in the widget's config
under the ``text`` key — the same shape the REST path validates
(``validate_text_config`` in src/api/schemas.py). The dashboard defaults to
the one in state or the one the user is looking at (view_context).
Owner-only, like the other primitives.
"""

from typing import Annotated, Dict, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import (
    dashboard_updated_command,
    error_command,
    load_editable_dashboard,
    resolve_dashboard_id,
)
from src.api.repositories import dashboard_writer
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

EMPTY_TEXT_MESSAGE = (
    "text is empty. Compose the markdown note first, then call "
    "add_text_widget with it."
)


def _normalize_text(text: Optional[str]) -> Optional[str]:
    """Strip surrounding whitespace; None when nothing remains."""
    if not text:
        return None
    return text.strip() or None


def _widget_config(text: str) -> dict:
    """The text-widget config contract: exactly ``{"text": markdown}``."""
    return {"text": text}


@tool("add_text_widget")
async def add_text_widget(
    text: str,
    dashboard_id: Optional[str] = None,
    position: Optional[int] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Add a text widget (a markdown note) to a dashboard.

    `text` is the widget's markdown body — compose it yourself: a concise
    note, summary or section intro; headings go in the markdown (there is
    no separate title). `dashboard_id` defaults to the dashboard in state
    or the one the user is currently viewing; `position` optionally places
    the widget (default: appended at the end). Only dashboards the user
    owns can be edited.
    """
    state = state or {}

    body = _normalize_text(text)
    if body is None:
        return error_command(EMPTY_TEXT_MESSAGE, tool_call_id)

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard to add to. Create one with create_dashboard, or "
            "pass a dashboard_id.",
            tool_call_id,
        )

    logger.info(
        "add_text_widget tool called",
        dashboard_id=str(target_dashboard),
        text_chars=len(body),
    )

    dashboard = await load_editable_dashboard(
        target_dashboard, "add_text_widget"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    widget_id = await dashboard_writer.add_widget(
        str(target_dashboard),
        widget_type="text",
        config=_widget_config(body),
        position=position,
    )
    if widget_id is None:
        return error_command(
            f"Dashboard {target_dashboard} disappeared before the text "
            "widget could be added.",
            tool_call_id,
        )

    return dashboard_updated_command(
        dashboard.id,
        dashboard.name,
        (
            f"Added text widget {widget_id} to dashboard "
            f"'{dashboard.name}' ({dashboard.id}). Use this widget id with "
            "edit_text_widget to change the note later."
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=add_text_widget,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_text_widget(text, dashboard_id?, position?): add a markdown "
        "text widget to a dashboard. Compose the markdown yourself — a "
        "concise note, summary of findings from this conversation, or "
        "section intro; do not paste raw data. Dashboard defaults to the "
        "one in state or on screen. Use when the user asks to add a note, "
        "description, summary or explanation to their dashboard."
    ),
)
