"""move_dashboard_widget — regroup a widget that is already on a dashboard.

The counterpart to the `section` argument the add tools take: those place a
widget as it goes on, this one moves one that is already there. Either into
a section (`section`) or back out to the ungrouped top level (`ungroup`);
`position` optionally picks the slot, otherwise the widget lands at the end
of its new container. Naming the container the widget is already in and
passing a `position` reorders it in place. Widget ids come from
`inspect_view_context`, which lists every widget with its id. Owner-only,
like the other primitives.
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
    resolve_section,
)
from src.api.repositories import dashboard_writer
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _describe(widget) -> str:
    """Short label for a widget in a reply — type plus what it points at."""
    if widget.widget_type == "insight":
        return f"insight widget {widget.id}"
    return f"{widget.widget_type} widget {widget.id}"


@tool("move_dashboard_widget")
async def move_dashboard_widget(
    widget_id: str,
    section: Optional[str] = None,
    ungroup: bool = False,
    position: Optional[int] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Move a widget into a dashboard section, or back out of one.

    `widget_id` names the widget — run `inspect_view_context` to list the
    dashboard's widgets with their ids. Pass either `section` (a section
    title or id) to move it into that section, or `ungroup=True` to move it
    back to the ungrouped top level; exactly one of the two. `position`
    optionally picks the slot within the new container — by default the
    widget goes to the end. To reorder a widget without regrouping it, name
    the container it is already in and pass a `position`. Only dashboards
    the user owns can be edited.
    """
    if bool(section) == bool(ungroup):
        return error_command(
            "Pass exactly one of `section` (to move the widget into that "
            "section) or `ungroup=True` (to move it back to the top level).",
            tool_call_id,
        )

    widget = await dashboard_writer.get_widget(widget_id)
    if widget is None:
        return error_command(
            f"Widget {widget_id} not found. Run inspect_view_context to "
            "list the dashboard's widgets with their ids.",
            tool_call_id,
        )

    # The ownership check runs against the widget's own dashboard, so a
    # widget on someone else's dashboard reads the same as a missing one.
    dashboard = await load_editable_dashboard(
        widget.dashboard_id, "move_dashboard_widget"
    )
    if dashboard is None:
        return error_command(
            f"Widget {widget_id} not found or its dashboard is not editable.",
            tool_call_id,
        )

    target_section = None
    if section:
        target_section, message = resolve_section(dashboard, section)
        if message:
            return error_command(message, tool_call_id)
        if target_section.id == widget.section_id and position is None:
            return error_command(
                f"{_describe(widget)} is already in section "
                f"'{target_section.title}' — nothing to move. Pass a "
                "position if you meant to reorder it within the section.",
                tool_call_id,
            )
    elif widget.section_id is None and position is None:
        return error_command(
            f"{_describe(widget)} is already ungrouped — nothing to move. "
            "Pass a position if you meant to reorder it at the top level.",
            tool_call_id,
        )

    logger.info(
        "move_dashboard_widget tool called",
        widget_id=str(widget.id),
        dashboard_id=str(dashboard.id),
        section_id=str(target_section.id) if target_section else None,
    )

    moved = await dashboard_writer.update_widget(
        widget.id,
        position=position,
        section_id=str(target_section.id) if target_section else None,
    )
    if not moved:
        return error_command(
            f"Widget {widget.id} disappeared before it could be moved.",
            tool_call_id,
        )

    destination = (
        f"section '{target_section.title}'"
        if target_section
        else "the top level (ungrouped)"
    )
    # Same container plus a position is a reorder, not a move; say so, or
    # the model reads back "moved" for a widget that never changed group.
    if (target_section.id if target_section else None) == widget.section_id:
        content = (
            f"Moved {_describe(widget)} to position {position} in "
            f"{destination} on dashboard '{dashboard.name}' "
            f"({dashboard.id})."
        )
    else:
        content = (
            f"Moved {_describe(widget)} to {destination} on dashboard "
            f"'{dashboard.name}' ({dashboard.id})."
        )
    return dashboard_updated_command(
        dashboard.id, dashboard.name, content, tool_call_id
    )


SPEC = ToolSpec(
    tool=move_dashboard_widget,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- move_dashboard_widget(widget_id, section?, ungroup?, position?): "
        "move a widget already on a dashboard into a section (`section` is a "
        "section title or id) or back out to the top level "
        "(`ungroup=True`) — exactly one of the two; naming the container "
        "it is already in plus a `position` reorders it in place. Widget "
        "ids come from inspect_view_context. Use when the user asks to "
        "move, regroup or reorder existing dashboard content."
    ),
)
