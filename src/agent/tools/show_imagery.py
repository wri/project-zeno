"""The Sentinel-2 imagery tool, plus the plumbing both imagery tools share.

Both imagery tools resolve the same AOI/date inputs and emit the same kind of
Command; only the provider they reach for differs. That shared part lives
here, so each tool stays a thin adapter over the provider classes.
"""

from datetime import date
from typing import Annotated, Dict, Optional, Union

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.i18n import t
from src.agent.imagery import (
    ImageryProviderResult,
    ImageryRequest,
    Sentinel2ImageryProvider,
)
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

SENTINEL2_PROVIDER = Sentinel2ImageryProvider()


def feedback(message: str, tool_call_id: Optional[str]) -> Command:
    """A message for the user that carries no imagery layer."""
    return Command(
        update={
            "messages": [
                ToolMessage(
                    message,
                    tool_call_id=tool_call_id,
                    status="success",
                    response_metadata={"msg_type": "human_feedback"},
                )
            ],
        },
    )


def provider_command(
    result: ImageryProviderResult, tool_call_id: Optional[str]
) -> Command:
    message = ToolMessage(
        result.message,
        tool_call_id=tool_call_id,
        status="success",
        response_metadata={"msg_type": "human_feedback"}
        if result.status == "error"
        else {},
    )
    update = {"messages": [message]}
    if result.imagery is not None:
        update["imagery"] = result.imagery.model_dump()
    return Command(update=update)


async def build_request(
    state: Optional[dict],
    target_date: Optional[str],
    tool_call_id: Optional[str],
    window_days: Optional[int] = None,
    max_cloud_cover: Optional[int] = None,
) -> Union[ImageryRequest, Command]:
    """The request for this call, or a Command explaining why there isn't one.

    Returning the failure as a Command keeps both tools' happy paths flat.
    """
    language = (state or {}).get("language") or DEFAULT_LANGUAGE
    aois = ((state or {}).get("aoi_selection") or {}).get("aois") or []
    if not aois:
        return feedback(await t("show_imagery.no_aoi", language), tool_call_id)

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            return feedback(
                await t(
                    "show_imagery.invalid_date",
                    language,
                    target_date=target_date,
                ),
                tool_call_id,
            )

    return ImageryRequest(
        aois=aois,
        target_date=parsed_date,
        language=language,
        window_days=window_days,
        max_cloud_cover=max_cloud_cover,
    )


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
