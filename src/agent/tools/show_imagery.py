from typing import Annotated, Dict, Optional

from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.imagery import ImageryRequest, Sentinel2ImageryProvider
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.imagery_support import build_request, provider_command
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

SENTINEL2_PROVIDER = Sentinel2ImageryProvider()


@tool("show_imagery")
async def show_imagery(
    state: Annotated[Dict, InjectedState],
    target_date: Optional[str] = None,
    window_days: Optional[int] = None,
    max_cloud_cover: Optional[int] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Show a Sentinel-2 satellite imagery layer on the map for the AOI in state.

    Sentinel-2 is global and continuous, so this serves any place and any
    date. target_date (YYYY-MM-DD) is the date the imagery should be closest
    to; pass null when the user requests no date, which shows approximately
    the previous two weeks. window_days (default 7, max 183) widens the
    search to +/-N days around target_date; max_cloud_cover (default 20,
    percent) loosens the cloud filter. Only raise them when the defaults find
    no scenes and the user agrees. Run pick_aoi first. Regional areas only.
    """
    logger.info("show_imagery tool called")
    request = await build_request(
        state, target_date, tool_call_id, window_days, max_cloud_cover
    )
    if not isinstance(request, ImageryRequest):
        return request

    logger.info(
        "SHOW-IMAGERY-TOOL: AOI: %s, Target date: %s",
        [aoi["name"] for aoi in request.aois],
        target_date,
    )
    return provider_command(
        await SENTINEL2_PROVIDER.get_imagery(request), tool_call_id
    )


SPEC = ToolSpec(
    tool=show_imagery,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- show_imagery: show Sentinel-2 imagery for the AOI in state. With "
        "no date it covers approximately the previous two weeks. Run "
        "pick_aoi first."
    ),
)
