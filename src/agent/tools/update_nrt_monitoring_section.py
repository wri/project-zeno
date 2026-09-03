"""update_nrt_monitoring_section — move a monitoring section to a new window.

The counterpart to add_nrt_monitoring_section: that one builds a section for
a period, this one moves an existing section to a different period. It is not
an edit of the section's content in the sense the seal forbids — the whole
section is rebuilt on the recipe's own terms, chart, layer and imagery
together, and its title and description are rewritten because they state the
period.

Changing the window changes every figure the user is looking at, so the tool
refuses to run until the user has actually agreed to it: `confirmed=True` is
only legitimate after a send_nudge the user answered.
"""

from typing import Annotated, Dict, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.language import DEFAULT_LANGUAGE
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import (
    dashboard_updated_command,
    error_command,
    load_editable_dashboard,
    require_current_user_id,
    resolve_dashboard_id,
)
from src.api.services.nrt_monitoring import (
    MAX_DAYS,
    AnalyticsFailedError,
    nrt_sections,
    refresh_nrt_section,
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


def _describe_window(section) -> str:
    window = section.config or {}
    if window.get("start_date") and window.get("end_date"):
        return f"{window['start_date']} to {window['end_date']}"
    return "an unrecorded period"


@tool("update_nrt_monitoring_section")
async def update_nrt_monitoring_section(
    days: int,
    confirmed: bool = False,
    section: Optional[str] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Move a near-real-time monitoring section to a different time window.

    `days` is the new window, counted back from today (1-365). Every widget
    in the section moves to it together — the alerts chart, the alerts map
    and the satellite imagery — and the section's title and description are
    rewritten to match.

    You MUST confirm the change with the user before applying it: call
    send_nudge first, then call this again with `confirmed=True`. Without
    that this tool does nothing.

    `section` names the section by title or id when the dashboard has more
    than one monitoring section; `dashboard_id` defaults to the dashboard in
    state or the one the user is viewing. Rebuilding takes a while — say what
    you are doing first.
    """
    state = state or {}

    if days < 1 or days > MAX_DAYS:
        return error_command(
            f"days must be between 1 and {MAX_DAYS}.", tool_call_id
        )

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard in view. Pass a dashboard_id, or run "
            "inspect_view_context to see what is on screen.",
            tool_call_id,
        )

    dashboard = await load_editable_dashboard(
        target_dashboard, "update_nrt_monitoring_section"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    candidates = nrt_sections(dashboard)
    if not candidates:
        return error_command(
            f"Dashboard '{dashboard.name}' has no near-real-time monitoring "
            "section. Build one with add_nrt_monitoring_section.",
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
                f"No monitoring section '{section}' on dashboard "
                f"'{dashboard.name}'. Existing ones: "
                + "; ".join(f"'{r.title}' ({r.id})" for r in candidates)
                + ".",
                tool_call_id,
            )
    elif len(candidates) > 1:
        return error_command(
            f"Dashboard '{dashboard.name}' has more than one monitoring "
            "section — name the one to update with `section`: "
            + "; ".join(
                f"'{r.title}' ({r.id}, {_describe_window(r)})"
                for r in candidates
            )
            + ".",
            tool_call_id,
        )
    else:
        target = candidates[0]

    if not confirmed:
        return error_command(
            f"Section '{target.title}' currently covers "
            f"{_describe_window(target)}. {CONFIRM_FIRST}",
            tool_call_id,
        )

    if not dashboard.aois:
        return error_command(
            f"Dashboard '{dashboard.name}' has no area to monitor.",
            tool_call_id,
        )

    aoi = dashboard.aois[0]
    logger.info(
        "update_nrt_monitoring_section tool called",
        dashboard_id=str(target_dashboard),
        section_id=str(target.id),
        days=days,
    )

    try:
        result = await refresh_nrt_section(
            str(target.id),
            {
                "source": aoi.source,
                "src_id": aoi.src_id,
                "subtype": aoi.subtype,
                "name": aoi.name,
            },
            user_id=require_current_user_id("update_nrt_monitoring_section"),
            days=days,
            language=state.get("language") or DEFAULT_LANGUAGE,
        )
    except AnalyticsFailedError as error:
        return error_command(
            f"Could not retrieve alert data for '{aoi.name}': {error}",
            tool_call_id,
        )
    except ValueError:
        return error_command(
            f"Section {target.id} disappeared before it could be updated.",
            tool_call_id,
        )

    caveat = (
        f" Satellite imagery was not added: {result.warnings[0]}"
        if result.warnings
        else ""
    )
    return dashboard_updated_command(
        dashboard.id,
        dashboard.name,
        (
            f"Moved the monitoring section ({result.section_id}) to "
            f"{result.start_date}–{result.end_date} ({result.days} days) on "
            f"dashboard '{dashboard.name}'. Every widget now covers that "
            f"period, with {len(result.widget_ids)} widgets in the "
            f"section.{caveat}"
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=update_nrt_monitoring_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- update_nrt_monitoring_section(days, confirmed, section?, "
        "dashboard_id?): move a near-real-time monitoring section to a "
        "different time window, rebuilding every widget in it for the new "
        "period. Confirm with the user via send_nudge first, then call with "
        "confirmed=True. Use when the user asks to change the period, date "
        "range or time window of a monitoring section."
    ),
)
