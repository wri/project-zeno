from dataclasses import replace
from typing import Annotated, Dict, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.imagery import (
    ImageryRequest,
    PlanetImageryProvider,
    Sentinel2ImageryProvider,
)
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.show_imagery import build_request, provider_command
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

PLANET_PROVIDER = PlanetImageryProvider()
SENTINEL2_PROVIDER = Sentinel2ImageryProvider()

FALLBACK_PREFIX = (
    "Planet imagery is not available for this area and month, so Sentinel-2 "
    "is shown instead. "
)
BEFORE_EARLIEST_PREFIX = (
    "Planet imagery is only available from September 2020, so Sentinel-2 "
    "is shown instead. "
)


@tool("show_planet_imagery")
async def show_planet_imagery(
    state: Annotated[Dict, InjectedState],
    target_date: Optional[str] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Show Planet's high-resolution monthly mosaic for the AOI in state.

    Use this to inspect Integrated Disturbance Alerts up close in the
    Amazon biome. Planet renders only inside a 500 m buffer around alerts
    from the past 2 years, so it is blank away from alerts and is not a
    general basemap. Mosaics start in September 2020; each month is
    published around the 15th of the following month, so there is never a
    current-month mosaic.
    target_date (YYYY-MM-DD) selects the month; pass null to get the most
    recent available month, and tell the user it is the most recently
    available Planet imagery. Outside the footprint, or for
    "latest"/"recent" imagery, use show_imagery instead — this tool falls
    back to Sentinel-2 and says so. Run pick_aoi first. Regional areas only.
    """
    logger.info("show_planet_imagery tool called")
    request = await build_request(state, target_date, tool_call_id)
    if not isinstance(request, ImageryRequest):
        return request

    logger.info(
        "SHOW-PLANET-IMAGERY-TOOL: AOI: %s, Target date: %s",
        [aoi["name"] for aoi in request.aois],
        target_date,
    )

    servable = (
        PLANET_PROVIDER.covers(request.aois)
        and not PLANET_PROVIDER.is_newer_than_latest_available(
            request.target_date
        )
        and not PLANET_PROVIDER.is_before_earliest_available(
            request.target_date
        )
    )
    if servable:
        return provider_command(
            await PLANET_PROVIDER.get_imagery(request), tool_call_id
        )

    prefix = (
        BEFORE_EARLIEST_PREFIX
        if PLANET_PROVIDER.is_before_earliest_available(request.target_date)
        else FALLBACK_PREFIX
    )
    # Still show imagery rather than dead-ending with no layer, and keep the
    # reason attached even when Sentinel-2 itself fails.
    result = await SENTINEL2_PROVIDER.get_imagery(request)
    return provider_command(
        replace(result, message=f"{prefix}{result.message}"),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=show_planet_imagery,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- show_planet_imagery: show Planet's high-resolution monthly mosaic "
        "for the AOI in state, for inspecting Integrated Disturbance Alerts "
        "up close in the Amazon. Blank away from alerts; available from "
        "September 2020, each month published around the 15th of the next "
        "month. Use show_imagery for recent or non-Amazon imagery."
    ),
)
