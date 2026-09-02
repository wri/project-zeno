"""add_dashboard_section — create a titled group of widgets on a dashboard.

A section is the one level of hierarchy a dashboard has: widgets either sit
in a section or stay ungrouped at the top. This tool is a deterministic DB
write, like the other dashboard primitives — it creates the empty section;
widgets join it by passing `section` to add_to_dashboard, add_text_widget or
add_map_widget. The dashboard defaults to the one in state or the one the
user is looking at (view_context). Owner-only.
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


def _normalize(text: Optional[str]) -> Optional[str]:
    """Strip surrounding whitespace; None when nothing remains."""
    if not text:
        return None
    return text.strip() or None


@tool("add_dashboard_section")
async def add_dashboard_section(
    title: str,
    description: Optional[str] = None,
    dashboard_id: Optional[str] = None,
    position: Optional[int] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Create a section (a titled group of widgets) on a dashboard.

    `title` is the section heading — short and topical, e.g. "Deforestation"
    or "Land cover". `description` optionally captures what the section is
    for in a line or two; compose it yourself. `dashboard_id` defaults to
    the dashboard in state or the one the user is currently viewing;
    `position` optionally places the section (default: appended last). The
    section starts empty — put widgets in it by passing `section` to
    add_to_dashboard, add_text_widget or add_map_widget.
    """
    state = state or {}

    heading = _normalize(title)
    if heading is None:
        return error_command(
            "title is empty. Give the section a short topical heading.",
            tool_call_id,
        )

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard to add a section to. Create one with "
            "create_dashboard, or pass a dashboard_id.",
            tool_call_id,
        )

    logger.info(
        "add_dashboard_section tool called",
        dashboard_id=str(target_dashboard),
        title=heading,
    )

    dashboard = await load_editable_dashboard(
        target_dashboard, "add_dashboard_section"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    existing = next(
        (
            section
            for section in dashboard.sections or []
            if section.title.casefold() == heading.casefold()
        ),
        None,
    )
    if existing is not None:
        return error_command(
            f"Dashboard '{dashboard.name}' already has a section "
            f"'{existing.title}' ({existing.id}) — do not create a second "
            "one. Add widgets to it with section="
            f"'{existing.title}', or use edit_dashboard_section to change "
            "its title or description.",
            tool_call_id,
        )

    section_id = await dashboard_writer.add_section(
        str(target_dashboard),
        title=heading,
        description=_normalize(description),
        position=position,
    )
    if section_id is None:
        return error_command(
            f"Dashboard {target_dashboard} disappeared before the section "
            "could be added.",
            tool_call_id,
        )

    return dashboard_updated_command(
        dashboard.id,
        dashboard.name,
        (
            f"Added section '{heading}' ({section_id}) to dashboard "
            f"'{dashboard.name}' ({dashboard.id}). It is empty — pass "
            f"section='{heading}' when adding widgets to place them here."
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=add_dashboard_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_dashboard_section(title, description?, dashboard_id?, "
        "position?): create a titled group of widgets on a dashboard. "
        "Widgets join it via the `section` argument of add_to_dashboard / "
        "add_text_widget / add_map_widget. Dashboard defaults to the one in "
        "state or on screen. Use when the user asks to group, organize or "
        "structure a dashboard, or when you are composing a dashboard that "
        "covers several distinct topics."
    ),
)
