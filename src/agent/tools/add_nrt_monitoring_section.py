"""add_nrt_monitoring_section — build a monitoring section in one call.

Unlike the other dashboard primitives, this tool does not snapshot work the
conversation already did: it runs the whole recipe itself (pull the alert
data, build the default chart, resolve the alerts layer, build a Sentinel-2
mosaic, write the section's title and description) and writes the result as
one sealed section. So it needs neither pick_dataset nor show_imagery to have
run — only a dashboard with an area.

The section it writes is read-only afterwards. Editing tools refuse it; to
change one, delete it and build another.
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
    DEFAULT_DAYS,
    AnalyticsFailedError,
    build_nrt_section,
    find_existing_section,
    resolve_period,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


@tool("add_nrt_monitoring_section")
async def add_nrt_monitoring_section(
    dashboard_id: Optional[str] = None,
    days: Optional[int] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Add a near-real-time monitoring section to a dashboard.

    Builds three widgets for the dashboard's area in one step: a chart of
    integrated disturbance alerts over the period, a map of those alerts,
    and satellite imagery of the same area and period. It pulls the data
    itself — do NOT run pick_dataset, pull_data, generate_insights or
    show_imagery first. `days` is the length of the alert window counted
    back from today (default 90, max 365). `dashboard_id` defaults to the
    dashboard in state or the one the user is viewing.

    The section is read-only once built; to change it, delete it and build a
    new one. Satellite imagery is skipped for areas that are too large or
    periods with no clear scenes — the section is still built.
    """
    state = state or {}
    window_days = days if days is not None else DEFAULT_DAYS
    if window_days < 1 or window_days > 365:
        return error_command("days must be between 1 and 365.", tool_call_id)

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard to add the monitoring section to. Create one with "
            "create_dashboard, or pass a dashboard_id.",
            tool_call_id,
        )

    dashboard = await load_editable_dashboard(
        target_dashboard, "add_nrt_monitoring_section"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )
    if not dashboard.aois:
        return error_command(
            f"Dashboard '{dashboard.name}' has no area to monitor.",
            tool_call_id,
        )

    start_date, end_date = resolve_period(window_days)
    existing = find_existing_section(dashboard, start_date, end_date)
    if existing is not None:
        return error_command(
            f"Dashboard '{dashboard.name}' already has the monitoring "
            f"section '{existing.title}' ({existing.id}) for this period. "
            "Tell the user it is already there rather than building a "
            "second one; to rebuild it, delete that section first.",
            tool_call_id,
        )

    aoi = dashboard.aois[0]
    logger.info(
        "add_nrt_monitoring_section tool called",
        dashboard_id=str(target_dashboard),
        days=window_days,
    )

    try:
        result = await build_nrt_section(
            str(target_dashboard),
            {
                "source": aoi.source,
                "src_id": aoi.src_id,
                "subtype": aoi.subtype,
                "name": aoi.name,
            },
            user_id=require_current_user_id("add_nrt_monitoring_section"),
            days=window_days,
            language=state.get("language") or DEFAULT_LANGUAGE,
        )
    except AnalyticsFailedError as error:
        return error_command(
            f"Could not retrieve alert data for '{aoi.name}': {error}",
            tool_call_id,
        )
    except ValueError:
        return error_command(
            f"Dashboard {target_dashboard} disappeared before the section "
            "could be added.",
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
            f"Added a near-real-time monitoring section ({result.section_id}) "
            f"for '{aoi.name}' covering {result.start_date} to "
            f"{result.end_date} to dashboard '{dashboard.name}' "
            f"({dashboard.id}), with {len(result.widget_ids)} widgets. The "
            "section is read-only — it cannot be edited, only deleted and "
            f"rebuilt.{caveat}"
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=add_nrt_monitoring_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_nrt_monitoring_section(dashboard_id?, days?): build a "
        "near-real-time monitoring section — an alerts chart, an alerts map "
        "and satellite imagery for the dashboard's area — in one call. It "
        "pulls its own data, so do NOT run pick_dataset, pull_data, "
        "generate_insights or show_imagery for it. The section it writes is "
        "read-only. Use when the user asks to monitor an area, or for "
        "recent/near-real-time disturbance on a dashboard."
    ),
)
