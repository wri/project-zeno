"""edit_dashboard_section — retitle a section or restate what it is for.

The companion to add_dashboard_section. `section` names one of the
dashboard's sections by title or id; when the dashboard has exactly one
section it can be left out. Owner-only, like the other dashboard primitives.
"""

from typing import Annotated, Dict, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.add_dashboard_section import _normalize
from src.agent.tools.common import (
    dashboard_updated_command,
    error_command,
    format_sections,
    load_editable_dashboard,
    resolve_dashboard_id,
    resolve_section,
)
from src.api.repositories import dashboard_writer
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _select_section(dashboard, section: Optional[str]):
    """The section to edit, as ``(section_orm, error_message)``.

    With no `section` argument the dashboard's only section is the obvious
    target; with several the error lists them so the model can retry.
    """
    if section:
        return resolve_section(dashboard, section)
    sections = dashboard.sections or []
    if not sections:
        return None, (
            f"Dashboard '{dashboard.name}' has no sections. Create one with "
            "add_dashboard_section instead."
        )
    if len(sections) > 1:
        return None, (
            "Multiple sections on this dashboard — pass `section` to pick "
            f"one. Sections: {format_sections(dashboard)}"
        )
    return sections[0], None


@tool("edit_dashboard_section")
async def edit_dashboard_section(
    section: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Change a section's title and/or its description.

    `section` names the section to edit by title or id; it defaults to the
    dashboard's only section, and when several exist the error lists them so
    you can retry. `title` is the new heading, `description` the new intent
    text (a full replacement, not an append) — pass at least one of them.
    `dashboard_id` defaults to the dashboard in state or the one the user is
    currently viewing. Only dashboards the user owns can be edited.
    """
    state = state or {}

    new_title = _normalize(title)
    new_description = _normalize(description)
    if new_title is None and new_description is None:
        return error_command(
            "Nothing to change. Pass a new title, a new description, or both.",
            tool_call_id,
        )

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard to edit. Pass a dashboard_id.", tool_call_id
        )

    dashboard = await load_editable_dashboard(
        target_dashboard, "edit_dashboard_section"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    row, message = _select_section(dashboard, section)
    if row is None:
        return error_command(message, tool_call_id)

    logger.info(
        "edit_dashboard_section tool called",
        dashboard_id=str(dashboard.id),
        section_id=str(row.id),
    )

    updated = await dashboard_writer.update_section(
        row.id,
        title=new_title,
        description=(
            new_description
            if new_description is not None
            else dashboard_writer.UNSET
        ),
    )
    if not updated:
        return error_command(
            f"Section {row.id} disappeared before it could be edited.",
            tool_call_id,
        )

    return dashboard_updated_command(
        dashboard.id,
        dashboard.name,
        (
            f"Updated section '{new_title or row.title}' ({row.id}) on "
            f"dashboard '{dashboard.name}' ({dashboard.id})."
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=edit_dashboard_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- edit_dashboard_section(section?, title?, description?, "
        "dashboard_id?): rename a dashboard section or replace its "
        "description. `section` is a section title or id; it defaults to "
        "the dashboard's only section. Use when the user asks to rename a "
        "section or change what it says it is for."
    ),
)
