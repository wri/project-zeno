"""Two dashboard tools that replace seven, for the ``concise-replies`` flag.

``add_dashboard_item`` adds an insight, a map, a text block or a section.
``edit_dashboard_item`` changes a text block or a section, or moves a
widget. Each one dispatches on ``kind`` to the tool that does the work, so
the behaviour and the messages are those of the seven tools. Only the tool
schemas that the model sees are smaller (docs/concise-agent-plan.md,
option A).

The arguments are flat: a schema with a nested object for each kind is
less reliable with Gemini function calling. The checks that a schema with
``required`` fields would make are here, as error messages that name the
missing argument.
"""

import re
from typing import Annotated, Dict, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.add_dashboard_section import add_dashboard_section
from src.agent.tools.add_map_widget import add_map_widget
from src.agent.tools.add_text_widget import add_text_widget
from src.agent.tools.add_to_dashboard import add_to_dashboard
from src.agent.tools.common import error_command
from src.agent.tools.create_dashboard import create_dashboard
from src.agent.tools.edit_dashboard_section import edit_dashboard_section
from src.agent.tools.edit_text_widget import edit_text_widget
from src.agent.tools.move_dashboard_widget import move_dashboard_widget
from src.api.schemas import SECTION_TITLE_MAX_LENGTH

# The tools that the two tools replace, in the order of ALL_SPECS.
REPLACED_TOOLS = (
    "add_to_dashboard",
    "add_map_widget",
    "add_text_widget",
    "edit_text_widget",
    "add_dashboard_section",
    "edit_dashboard_section",
    "move_dashboard_widget",
)


# The old tool names in the replies of the seven tools, and the call that
# does the same work now.
_NEW_NAMES = {
    "add_to_dashboard": 'add_dashboard_item(kind="insight")',
    "add_map_widget": 'add_dashboard_item(kind="map")',
    "add_text_widget": 'add_dashboard_item(kind="text")',
    "add_dashboard_section": 'add_dashboard_item(kind="section")',
    "edit_text_widget": 'edit_dashboard_item(kind="text")',
    "edit_dashboard_section": 'edit_dashboard_item(kind="section")',
    "move_dashboard_widget": 'edit_dashboard_item(kind="move")',
}
_NAME_PATTERN = re.compile(r"\b(" + "|".join(_NEW_NAMES) + r")\b(\(\))?")


def _rename(command: Command) -> Command:
    """Replace the old tool names in the tool messages of ``command``."""
    update = command.update if isinstance(command.update, dict) else None
    for message in (update or {}).get("messages") or []:
        if isinstance(message, ToolMessage) and isinstance(
            message.content, str
        ):
            message.content = _NAME_PATTERN.sub(
                lambda m: _NEW_NAMES[m.group(1)], message.content
            )
    return command


def _missing(name: str, kind: str, tool_call_id: Optional[str]) -> Command:
    return error_command(
        f"`{name}` is required when kind is '{kind}'.", tool_call_id
    )


def _title_too_long(title: Optional[str]) -> bool:
    return title is not None and len(title) > SECTION_TITLE_MAX_LENGTH


@tool("add_dashboard_item")
async def add_dashboard_item(
    kind: Literal["insight", "map", "text", "section"],
    dashboard_id: Optional[str] = None,
    section: Optional[str] = None,
    insight_id: Optional[str] = None,
    layer: Optional[Literal["dataset", "imagery"]] = None,
    text: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    position: Optional[int] = None,
    state: Annotated[Optional[Dict], InjectedState] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Add an item to a dashboard."""
    common = {
        "dashboard_id": dashboard_id,
        "state": state,
        "tool_call_id": tool_call_id,
    }
    if kind == "insight":
        return _rename(
            await add_to_dashboard.coroutine(
                insight_id=insight_id, section=section, **common
            )
        )
    if kind == "map":
        if not layer:
            return _missing("layer", kind, tool_call_id)
        return _rename(
            await add_map_widget.coroutine(
                layer=layer, title=title, section=section, **common
            )
        )
    if kind == "text":
        if not text:
            return _missing("text", kind, tool_call_id)
        return _rename(
            await add_text_widget.coroutine(
                text=text, position=position, section=section, **common
            )
        )
    if kind == "section":
        if not title:
            return _missing("title", kind, tool_call_id)
        if _title_too_long(title):
            return error_command(
                f"`title` has more than {SECTION_TITLE_MAX_LENGTH} "
                "characters.",
                tool_call_id,
            )
        return _rename(
            await add_dashboard_section.coroutine(
                title=title,
                description=description,
                position=position,
                **common,
            )
        )
    return error_command(f"Unknown kind '{kind}'.", tool_call_id)


@tool("edit_dashboard_item")
async def edit_dashboard_item(
    kind: Literal["text", "section", "move"],
    dashboard_id: Optional[str] = None,
    widget_id: Optional[str] = None,
    section: Optional[str] = None,
    text: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    ungroup: bool = False,
    position: Optional[int] = None,
    state: Annotated[Optional[Dict], InjectedState] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Change an item of a dashboard."""
    if kind == "text":
        if not text:
            return _missing("text", kind, tool_call_id)
        return _rename(
            await edit_text_widget.coroutine(
                text=text,
                widget_id=widget_id,
                dashboard_id=dashboard_id,
                state=state,
                tool_call_id=tool_call_id,
            )
        )
    if kind == "section":
        if _title_too_long(title):
            return error_command(
                f"`title` has more than {SECTION_TITLE_MAX_LENGTH} "
                "characters.",
                tool_call_id,
            )
        return _rename(
            await edit_dashboard_section.coroutine(
                section=section,
                title=title,
                description=description,
                dashboard_id=dashboard_id,
                state=state,
                tool_call_id=tool_call_id,
            )
        )
    if kind == "move":
        if not widget_id:
            return _missing("widget_id", kind, tool_call_id)
        return _rename(
            await move_dashboard_widget.coroutine(
                widget_id=widget_id,
                section=section,
                ungroup=ungroup,
                position=position,
                state=state,
                tool_call_id=tool_call_id,
            )
        )
    return error_command(f"Unknown kind '{kind}'.", tool_call_id)


_DEFAULT_DASHBOARD = (
    "`dashboard_id` defaults to the dashboard in state or on screen. Only "
    "the user's own dashboards can be edited."
)

ADD_DASHBOARD_ITEM_DESCRIPTION = (
    "Add one item to a dashboard. `section` (a section title or id) puts an "
    "insight, map or text in a section; without it the item is ungrouped. "
    '`kind="insight"`: an insight as a widget; `insight_id` defaults to the '
    "current insight in state, and it must be one the user can see. "
    '`kind="map"`: `layer="dataset"` is the selected dataset layer '
    '(pick_dataset first), `layer="imagery"` is the Sentinel-2 mosaic from '
    "show_imagery; `title` overrides the header. "
    '`kind="text"`: a markdown note in `text`, written by you: short, any '
    "heading in the markdown, no raw data; `position` places it (default "
    'last). `kind="section"`: an empty section; `title` short and topical, '
    'for example "Deforestation"; `description` optional, one or two lines '
    "on its purpose; `position` default last. " + _DEFAULT_DASHBOARD
)

EDIT_DASHBOARD_ITEM_DESCRIPTION = (
    "Change one item of a dashboard. "
    '`kind="text"`: replace all the markdown of a text widget with `text`; '
    "`widget_id` defaults to the only text widget (with several, the error "
    'lists their ids). `kind="section"`: change the `title` or the '
    "`description` of a section, or both (each a full replacement); "
    "`section` (a title or id) defaults to the only section. "
    '`kind="move"`: move the widget `widget_id` into `section` or back to '
    "the top level (`ungroup=true`), exactly one of the two; `position` sets "
    "the slot (default last); to reorder only, name the section it is in. "
    "Get widget ids from inspect_view_context. " + _DEFAULT_DASHBOARD
)

add_dashboard_item.description = ADD_DASHBOARD_ITEM_DESCRIPTION
edit_dashboard_item.description = EDIT_DASHBOARD_ITEM_DESCRIPTION

ADD_SPEC = ToolSpec(
    tool=add_dashboard_item,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment="",
)
EDIT_SPEC = ToolSpec(
    tool=edit_dashboard_item,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment="",
)


@tool("create_dashboard")
async def create_dashboard_concise(
    name: Optional[str] = None,
    state: Annotated[Optional[Dict], InjectedState] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Create a dashboard for the AOI in state."""
    return _rename(
        await create_dashboard.coroutine(
            name=name, state=state, tool_call_id=tool_call_id
        )
    )
