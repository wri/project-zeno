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


@tool("show_planet_imagery")
async def show_planet_imagery(
    state: Annotated[Dict, InjectedState],
    target_date: Optional[str] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Show Planet's high-resolution monthly mosaic for the AOI in state.

    Use this to inspect integrated deforestation alerts up close in the
    Amazon. Planet renders only inside a buffer around those alerts within a
    limited Amazon footprint, so it is blank away from alerts and is not a
    general basemap. It publishes one mosaic per calendar month and only
    through the last complete month, so there is never a current-month or
    "latest" Planet mosaic. target_date (YYYY-MM-DD) selects the month; pass
    null to get the previous complete month. Outside the footprint, or for
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

    servable = PLANET_PROVIDER.covers(
        request.aois
    ) and not PLANET_PROVIDER.is_newer_than_last_full_month(
        request.target_date
    )
    if servable:
        return provider_command(
            await PLANET_PROVIDER.get_imagery(request), tool_call_id
        )

    # Still show imagery rather than dead-ending with no layer, and keep the
    # reason attached even when Sentinel-2 itself fails.
    result = await SENTINEL2_PROVIDER.get_imagery(request)
    return provider_command(
        replace(result, message=f"{FALLBACK_PREFIX}{result.message}"),
        tool_call_id,
    )


SPEC = ToolSpec(
    tool=show_planet_imagery,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- show_planet_imagery: show Planet's high-resolution monthly mosaic "
        "for the AOI in state, for inspecting integrated deforestation "
        "alerts up close in the Amazon. Blank away from alerts and never "
        "current-month; use show_imagery for recent or non-Amazon imagery."
    ),
)
