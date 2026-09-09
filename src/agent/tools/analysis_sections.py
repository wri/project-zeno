"""The agent's two doors onto the analysis templates.

An analysis template builds a whole dashboard section in one call — see
``src.api.services.analysis_templates``. These two tools are generic: they
resolve the dashboard, look the named template up in the registry, hand it
its own validated parameters and report the summary it wrote. Neither knows
what any template contains, so a new template needs no new tool and no
change here — it is one registry entry and one skill section.

Unlike the other dashboard primitives, these do not snapshot work the
conversation already did: the template does the work itself. So neither
needs pick_dataset or show_imagery to have run — only a dashboard with an
area.

A section a template writes is sealed afterwards: the editing tools refuse
its content. ``update_analysis_section`` is the one exception, and it
rebuilds the section rather than editing it.
"""

from typing import Annotated, Dict, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import ValidationError

from src.agent.language import DEFAULT_LANGUAGE
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import (
    dashboard_updated_command,
    error_command,
    load_editable_dashboard,
    require_current_user_id,
    resolve_dashboard_id,
)
from src.api.services.analysis_templates import registry
from src.api.services.analysis_templates.base import (
    AlreadyBuiltError,
    TemplateError,
    describe_window,
    templated_sections,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

CONFIRM_FIRST = (
    "Changing the window changes every number in the section, so ask first. "
    'Call send_nudge(nudge_type="time_range_choice", options=["Last 2 '
    'weeks", "Last 30 days", "Last 90 days"]) — or options that match what '
    "the user asked for — and wait for their answer. Call this tool again "
    "with confirmed=True only after they have chosen."
)


def _params(template, days: Optional[int]):
    """The template's own parameter object, from what the model passed.

    Each template states its defaults and its bounds in its parameter
    model, and refuses a parameter it does not take, so this is the only
    validation either tool needs.
    """
    given = {} if days is None else {"days": days}
    return template.params_model(**given)


def _caveats(result) -> str:
    """The warnings a build reported, as a sentence for the model."""
    if not result.warnings:
        return ""
    return " Not everything was available: " + " ".join(result.warnings)


@tool("add_analysis_section")
async def add_analysis_section(
    template: str,
    days: Optional[int] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Build a curated analysis section on a dashboard, in one call.

    `template` names the analysis template to run — see the
    `analysis-templates` skill for what each one builds. The template pulls
    its own data, so do NOT run pick_dataset, pull_data, generate_insights
    or show_imagery first. `days` is the period the section covers, counted
    back from today, and defaults to the template's own window.
    `dashboard_id` defaults to the dashboard in state or the one the user is
    viewing.

    The section's content is read-only once built. To put it on a different
    period use update_analysis_section; to change anything else, delete it
    and build a new one. It takes a while — say what you are doing first.
    """
    state = state or {}

    try:
        recipe = registry.get_template(template)
    except registry.UnknownTemplateError as error:
        return error_command(str(error), tool_call_id)

    try:
        params = _params(recipe, days)
    except ValidationError as error:
        return error_command(
            f"Those parameters do not fit the '{template}' template: "
            f"{error.errors()[0]['msg']}.",
            tool_call_id,
        )

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard to add the section to. Create one with "
            "create_dashboard, or pass a dashboard_id.",
            tool_call_id,
        )

    dashboard = await load_editable_dashboard(
        target_dashboard, "add_analysis_section"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    logger.info(
        "add_analysis_section tool called",
        template=template,
        dashboard_id=str(target_dashboard),
        params=params.model_dump(),
    )

    try:
        result = await recipe.build(
            dashboard,
            user_id=require_current_user_id("add_analysis_section"),
            params=params,
            language=state.get("language") or DEFAULT_LANGUAGE,
        )
    except AlreadyBuiltError as error:
        # Not a failure: the section the user asked for is already there.
        return error_command(
            f"{error} Tell the user it is already there rather than "
            "building a second one; to rebuild it, delete that section "
            "first.",
            tool_call_id,
        )
    except TemplateError as error:
        return error_command(str(error), tool_call_id)

    return dashboard_updated_command(
        dashboard.id,
        str(dashboard.name),
        (
            f"Added {result.summary} to dashboard '{dashboard.name}' "
            f"({dashboard.id}), as section {result.section_id}. The "
            "section's content is read-only: use update_analysis_section to "
            "move it to another period, or delete it to change anything "
            f"else.{_caveats(result)}"
        ),
        tool_call_id,
    )


@tool("update_analysis_section")
async def update_analysis_section(
    days: int,
    confirmed: bool = False,
    section: Optional[str] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Move a curated analysis section to a different time window.

    `days` is the new period, counted back from today. Every widget in the
    section moves to it together, and the section's title and description
    are rewritten to match — the template rebuilds the whole section.

    You MUST confirm the change with the user before applying it: call
    send_nudge first, then call this again with `confirmed=True`. Without
    that this tool does nothing.

    `section` names the section by title or id when the dashboard has more
    than one; `dashboard_id` defaults to the dashboard in state or the one
    the user is viewing. Rebuilding takes a while — say what you are doing
    first.
    """
    state = state or {}

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard in view. Pass a dashboard_id, or run "
            "inspect_view_context to see what is on screen.",
            tool_call_id,
        )

    dashboard = await load_editable_dashboard(
        target_dashboard, "update_analysis_section"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    candidates = templated_sections(dashboard)
    if not candidates:
        return error_command(
            f"Dashboard '{dashboard.name}' has no curated analysis section "
            "to move. Build one with add_analysis_section.",
            tool_call_id,
        )

    if section:
        wanted = str(section).strip()
        target = next(
            (
                row
                for row in candidates
                if str(row.id) == wanted
                or row.title.casefold() == wanted.casefold()
            ),
            None,
        )
        if target is None:
            return error_command(
                f"No curated section '{section}' on dashboard "
                f"'{dashboard.name}'. Existing ones: "
                + "; ".join(f"'{r.title}' ({r.id})" for r in candidates)
                + ".",
                tool_call_id,
            )
    elif len(candidates) > 1:
        return error_command(
            f"Dashboard '{dashboard.name}' has more than one curated "
            "section — name the one to update with `section`: "
            + "; ".join(
                f"'{r.title}' ({r.id}, {describe_window(r)})"
                for r in candidates
            )
            + ".",
            tool_call_id,
        )
    else:
        target = candidates[0]

    try:
        recipe = registry.get_template(str(target.type))
    except registry.UnknownTemplateError:
        return error_command(
            f"Section '{target.title}' was built by '{target.type}', which "
            "is no longer available, so it cannot be rebuilt. It can only "
            "be deleted.",
            tool_call_id,
        )

    try:
        params = _params(recipe, days)
    except ValidationError as error:
        return error_command(
            f"Those parameters do not fit the '{target.type}' template: "
            f"{error.errors()[0]['msg']}.",
            tool_call_id,
        )

    # The refusal is the guard, not the instruction above: a window change
    # replaces every figure on screen and deletes the previous ones, and a
    # model can retry past an instruction but not past a refusal.
    if not confirmed:
        return error_command(
            f"Section '{target.title}' currently covers "
            f"{describe_window(target)}. {CONFIRM_FIRST}",
            tool_call_id,
        )

    logger.info(
        "update_analysis_section tool called",
        template=str(target.type),
        dashboard_id=str(target_dashboard),
        section_id=str(target.id),
        params=params.model_dump(),
    )

    try:
        result = await recipe.refresh(
            target,
            dashboard,
            user_id=require_current_user_id("update_analysis_section"),
            params=params,
            language=state.get("language") or DEFAULT_LANGUAGE,
        )
    except TemplateError as error:
        return error_command(str(error), tool_call_id)

    return dashboard_updated_command(
        dashboard.id,
        str(dashboard.name),
        (
            f"Rebuilt section {result.section_id} on dashboard "
            f"'{dashboard.name}': {result.summary}.{_caveats(result)}"
        ),
        tool_call_id,
    )


ADD_SPEC = ToolSpec(
    tool=add_analysis_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_analysis_section(template, days?, dashboard_id?): build a "
        "curated analysis section — a chart, its map layers and the words "
        "that go with them — on a dashboard in one call. The template pulls "
        "its own data, so do NOT run pick_dataset, pull_data, "
        "generate_insights or show_imagery for it. The section it writes is "
        "read-only. Templates:\n" + registry.describe_templates()
    ),
)

UPDATE_SPEC = ToolSpec(
    tool=update_analysis_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- update_analysis_section(days, confirmed, section?, "
        "dashboard_id?): move a curated analysis section to a different "
        "time window, rebuilding every widget in it for the new period. "
        "Confirm with the user via send_nudge first, then call with "
        "confirmed=True. Use when the user asks to change the period, date "
        "range or time window of such a section."
    ),
)
