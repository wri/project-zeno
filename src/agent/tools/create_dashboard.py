"""create_dashboard — persist a dashboard for the AOI the user is working on.

A dashboard is a persistent, curated collection of insights for an area — a
complement to the map view. This tool is a deterministic DB write: it takes
the AOI selection already in state (run pick_aoi first if there is none) and
creates an empty dashboard for it; widgets are added separately via
add_to_dashboard. Orchestration ("build me a dashboard for X") lives in the
`dashboard` skill, not here.
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
    require_current_user_id,
)
from src.api.repositories import dashboard_writer
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _aoi_refs(aois: list[dict]) -> list[dict]:
    """Reduce state AOI dicts to the reference fields a dashboard stores."""
    return [
        {
            "source": aoi["source"],
            "src_id": aoi["src_id"],
            "subtype": aoi["subtype"],
            "name": aoi["name"],
        }
        for aoi in aois
    ]


@tool("create_dashboard")
async def create_dashboard(
    name: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Create a dashboard for the currently selected area.

    Uses the AOI already in state (run pick_aoi first if none is selected).
    The dashboard starts empty; add insights to it with add_to_dashboard.
    `name` defaults to the selected area's name.
    """
    user_id = require_current_user_id("create_dashboard")

    selection = (state or {}).get("aoi_selection") or {}
    aois = selection.get("aois") or []
    if not aois:
        return error_command(
            "No area selected. Run pick_aoi to select the area the "
            "dashboard is for, then create it.",
            tool_call_id,
        )
    if len(aois) > 1:
        return error_command(
            f"The current selection spans {len(aois)} areas, but dashboards "
            "currently cover a single area (a country, a state, a protected "
            "area). Ask the user which one area the dashboard is for and "
            "re-run pick_aoi.",
            tool_call_id,
        )

    dashboard_name = name or selection.get("name") or aois[0]["name"]

    dashboard_id = await dashboard_writer.create_dashboard(
        user_id=user_id,
        name=dashboard_name,
        aois=_aoi_refs(aois),
    )
    logger.info(
        "create_dashboard tool created dashboard",
        dashboard_id=dashboard_id,
        name=dashboard_name,
    )

    return dashboard_updated_command(
        dashboard_id,
        (
            f"Created dashboard '{dashboard_name}' ({dashboard_id}) for "
            f"{aois[0]['name']}. It is empty — use add_to_dashboard to "
            "add insights."
        ),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=create_dashboard,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- create_dashboard(name?): create a persistent dashboard for the "
        "currently selected area (run pick_aoi first if none). The dashboard "
        "starts empty; add insights with add_to_dashboard. Name defaults to "
        "the area's name. Use when the user asks to create/build a dashboard."
    ),
)
