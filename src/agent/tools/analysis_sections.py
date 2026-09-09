"""The agent's doors onto the analysis templates.

An analysis template builds a whole dashboard section in one call — see
``src.api.services.analysis_templates``. These tools are generic: they
resolve the dashboard, look the template up in the registry, hand it its own
validated parameters and report the summary it wrote. None of them knows
what any template contains or what its parameters mean, so a new template
needs no new tool and no change here — it is one registry entry and one
skill section.

Three verbs, because they are three different asks:

* ``add_analysis_section`` — build one.
* ``refresh_analysis_section`` — run an existing one again, unchanged, so it
  shows today's data. It takes no parameters at all: the section records
  what it was built with.
* ``reconfigure_analysis_section`` — rebuild an existing one for different
  parameters. That is the one the user has to agree to, because it answers a
  different question than the one on screen.

Unlike the other dashboard primitives, these do not snapshot work the
conversation already did: the template does the work itself. So none needs
pick_dataset or show_imagery to have run — only a dashboard with an area.

A section a template writes is sealed: the editing tools refuse its content.
The two rebuild verbs are the exception, and they replace the section
wholesale on the template's own terms rather than editing it.
"""

from typing import Annotated, Dict, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

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
    stored_params,
    templated_sections,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _parse_params(template, params: Optional[dict]):
    """The template's own parameter object, from what the model passed.

    Each template states its defaults and its bounds in its parameter model
    and refuses a parameter it does not take, so this is the only validation
    any of these tools needs.
    """
    return template.params_model(**(params or {}))


def _params_error(template, error: ValidationError, tool_call_id):
    """A refusal that says what the template does take, so the model can
    retry rather than guess again."""
    detail = error.errors()[0]
    field = ".".join(str(part) for part in detail.get("loc") or ()) or "params"
    return error_command(
        f"`{field}` does not fit the '{template.entry.name}' template: "
        f"{detail['msg']}. It takes — {template.entry.params_help}.",
        tool_call_id,
    )


def _caveats(result) -> str:
    """The warnings a build reported, as a sentence for the model."""
    if not result.warnings:
        return ""
    return " Not everything was available: " + " ".join(result.warnings)


async def _resolve_target(state, dashboard_id, section, tool_call_id, verb):
    """The dashboard, the templated section to act on and its template.

    Shared by the two rebuild verbs. Returns ``(dashboard, section,
    template)`` or ``(None, None, error_command)``.
    """
    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return (
            None,
            None,
            error_command(
                "No dashboard in view. Pass a dashboard_id, or run "
                "inspect_view_context to see what is on screen.",
                tool_call_id,
            ),
        )

    dashboard = await load_editable_dashboard(target_dashboard, verb)
    if dashboard is None:
        return (
            None,
            None,
            error_command(
                f"Dashboard {target_dashboard} not found or not editable.",
                tool_call_id,
            ),
        )

    candidates = templated_sections(dashboard)
    if not candidates:
        return (
            None,
            None,
            error_command(
                f"Dashboard '{dashboard.name}' has no curated analysis "
                "section. Build one with add_analysis_section.",
                tool_call_id,
            ),
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
            return (
                None,
                None,
                error_command(
                    f"No curated section '{section}' on dashboard "
                    f"'{dashboard.name}'. Existing ones: "
                    + "; ".join(f"'{r.title}' ({r.id})" for r in candidates)
                    + ".",
                    tool_call_id,
                ),
            )
    elif len(candidates) > 1:
        return (
            None,
            None,
            error_command(
                f"Dashboard '{dashboard.name}' has more than one curated "
                "section — name the one to act on with `section`: "
                + "; ".join(f"'{r.title}' ({r.id})" for r in candidates)
                + ".",
                tool_call_id,
            ),
        )
    else:
        target = candidates[0]

    try:
        template = registry.get_template(str(target.type))
    except registry.UnknownTemplateError:
        return (
            None,
            None,
            error_command(
                f"Section '{target.title}' was built by '{target.type}', "
                "which is no longer available, so it cannot be rebuilt. It "
                "can only be deleted.",
                tool_call_id,
            ),
        )
    return dashboard, target, template


async def _rebuild(
    dashboard, section, template, params: BaseModel, state, tool_call_id, verb
) -> Command:
    """Run a template over one of its own sections and report the result."""
    logger.info(
        f"{verb} tool called",
        template=template.entry.name,
        dashboard_id=str(dashboard.id),
        section_id=str(section.id),
        params=params.model_dump(),
    )
    try:
        result = await template.refresh(
            section,
            dashboard,
            user_id=require_current_user_id(verb),
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


@tool("add_analysis_section")
async def add_analysis_section(
    template: str,
    params: Optional[dict] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Build a curated analysis section on a dashboard, in one call.

    `template` names the analysis template to run. Each one lists what it
    builds and what it takes — see the `analysis-templates` skill. The
    template pulls its own data, so do NOT run pick_dataset, pull_data,
    generate_insights or show_imagery first.

    `params` is that template's own parameters as an object, e.g.
    `{"days": 30}`. Leave it out for the template's own defaults, which are
    the right answer whenever the user named none. `dashboard_id` defaults
    to the dashboard in state or the one the user is viewing.

    The section's content is read-only once built. Use
    refresh_analysis_section to bring it up to date, or
    reconfigure_analysis_section to rebuild it differently; to change
    anything else, delete it and build a new one. It takes a while — say
    what you are doing first.
    """
    state = state or {}

    try:
        recipe = registry.get_template(template)
    except registry.UnknownTemplateError as error:
        return error_command(str(error), tool_call_id)

    try:
        parsed = _parse_params(recipe, params)
    except ValidationError as error:
        return _params_error(recipe, error, tool_call_id)

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
        params=parsed.model_dump(),
    )

    try:
        result = await recipe.build(
            dashboard,
            user_id=require_current_user_id("add_analysis_section"),
            params=parsed,
            language=state.get("language") or DEFAULT_LANGUAGE,
        )
    except AlreadyBuiltError as error:
        # Not a failure: the section the user asked for is already there.
        return error_command(
            f"{error} Tell the user it is already there rather than "
            "building a second one. To bring it up to date use "
            "refresh_analysis_section.",
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
            "section's content is read-only: use refresh_analysis_section "
            "or reconfigure_analysis_section to rebuild it, or delete it to "
            f"change anything else.{_caveats(result)}"
        ),
        tool_call_id,
    )


@tool("refresh_analysis_section")
async def refresh_analysis_section(
    section: Optional[str] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Run a curated analysis section again, so it shows today's data.

    It keeps the parameters the section was built with — the same question,
    asked again now — so it takes none. Use it when the user asks to
    refresh, update or re-run a section, or asks whether anything has
    changed since. To ask a *different* question of it, e.g. over another
    period, use reconfigure_analysis_section.

    `section` names the section by title or id when the dashboard has more
    than one; `dashboard_id` defaults to the dashboard in state or the one
    the user is viewing. Rebuilding takes a while — say what you are doing
    first.
    """
    state = state or {}
    dashboard, target, template = await _resolve_target(
        state, dashboard_id, section, tool_call_id, "refresh_analysis_section"
    )
    if dashboard is None:
        return template  # the error command

    return await _rebuild(
        dashboard,
        target,
        template,
        stored_params(template, target),
        state,
        tool_call_id,
        "refresh_analysis_section",
    )


@tool("reconfigure_analysis_section")
async def reconfigure_analysis_section(
    params: dict,
    confirmed: bool = False,
    section: Optional[str] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Rebuild a curated analysis section for different parameters.

    `params` is the template's own parameters as an object, e.g.
    `{"days": 90}` — what each template takes is in the
    `analysis-templates` skill, and the tool tells you if you get it wrong.
    The whole section is rebuilt for them: every widget, and the title and
    description, which state what the section covers.

    You MUST confirm the change with the user before applying it: call
    send_nudge first, then call this again with `confirmed=True`. Without
    that this tool does nothing. Use refresh_analysis_section instead when
    the user only wants the section brought up to date — that needs no
    confirmation.

    `section` names the section by title or id when the dashboard has more
    than one; `dashboard_id` defaults to the dashboard in state or the one
    the user is viewing. Rebuilding takes a while — say what you are doing
    first.
    """
    state = state or {}
    dashboard, target, template = await _resolve_target(
        state,
        dashboard_id,
        section,
        tool_call_id,
        "reconfigure_analysis_section",
    )
    if dashboard is None:
        return template  # the error command

    try:
        parsed = _parse_params(template, params)
    except ValidationError as error:
        return _params_error(template, error, tool_call_id)

    # The refusal is the guard, not the instruction in the docstring: this
    # answers a different question than the one on screen, and the previous
    # answer is deleted. A model can retry past an instruction, not past a
    # refusal.
    if not confirmed:
        return error_command(
            f"Section '{target.title}' currently covers "
            f"{template.describe(target)}. Rebuilding it "
            f"{template.entry.change_warning}, so ask first: call send_nudge "
            "with the options that match what the user asked for, wait for "
            "their answer, then call this tool again with confirmed=True.",
            tool_call_id,
        )

    return await _rebuild(
        dashboard,
        target,
        template,
        parsed,
        state,
        tool_call_id,
        "reconfigure_analysis_section",
    )


ADD_SPEC = ToolSpec(
    tool=add_analysis_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_analysis_section(template, params?, dashboard_id?): build a "
        "curated analysis section — a chart, its map layers and the words "
        "that go with them — on a dashboard in one call. The template pulls "
        "its own data, so do NOT run pick_dataset, pull_data, "
        "generate_insights or show_imagery for it. The section it writes is "
        "read-only. Templates:\n" + registry.describe_templates()
    ),
)

REFRESH_SPEC = ToolSpec(
    tool=refresh_analysis_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- refresh_analysis_section(section?, dashboard_id?): run a curated "
        "analysis section again with the parameters it already has, so it "
        "shows today's data. Takes no parameters and needs no confirmation. "
        "Use when the user asks to refresh or re-run a section, or whether "
        "anything has changed since."
    ),
)

RECONFIGURE_SPEC = ToolSpec(
    tool=reconfigure_analysis_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- reconfigure_analysis_section(params, confirmed, section?, "
        "dashboard_id?): rebuild a curated analysis section for different "
        "parameters — another period, another threshold, whatever that "
        "template takes. Confirm with the user via send_nudge first, then "
        "call with confirmed=True. Use when the user asks to change what a "
        "section covers, not merely to bring it up to date."
    ),
)
