from dataclasses import replace
from datetime import date
from typing import Annotated, Dict, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.i18n import t
from src.agent.imagery import (
    ImageryProviderResult,
    ImageryRequest,
    PlanetImageryProvider,
    Sentinel2ImageryProvider,
)
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

PLANET_PROVIDER = PlanetImageryProvider()
SENTINEL2_PROVIDER = Sentinel2ImageryProvider()


def _feedback(message: str, tool_call_id: Optional[str]) -> Command:
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


def _provider_command(
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


@tool("show_imagery")
async def show_imagery(
    state: Annotated[Dict, InjectedState],
    target_date: Optional[str] = None,
    provider: Optional[Literal["sentinel-2", "planet"]] = None,
    window_days: Optional[int] = None,
    max_cloud_cover: Optional[int] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Show a satellite imagery layer on the map for the AOI in state.

    provider may be planet or sentinel-2. When provider and target_date are
    omitted, Sentinel-2 is shown for approximately the previous two weeks;
    Planet's previous complete month is suggested when available. A dated
    request uses Planet within coverage through the last complete month and
    Sentinel-2 otherwise. target_date (YYYY-MM-DD)
    selects the Planet month or the date Sentinel-2 imagery should be closest
    to; pass null when the user requests no date. window_days (default 7,
    max 183) widens the Sentinel-2
    search to ±N days around target_date; max_cloud_cover (default 20,
    percent) loosens the cloud filter. Only raise them when the defaults
    find no scenes and the user agrees. Run pick_aoi first. Regional
    areas only.
    """
    logger.info("show_imagery tool called")
    language = (state or {}).get("language") or DEFAULT_LANGUAGE
    aois = ((state or {}).get("aoi_selection") or {}).get("aois") or []
    if not aois:
        return _feedback(
            await t("show_imagery.no_aoi", language),
            tool_call_id,
        )

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            return _feedback(
                await t(
                    "show_imagery.invalid_date",
                    language,
                    target_date=target_date,
                ),
                tool_call_id,
            )

    aoi_names = [aoi["name"] for aoi in aois]
    logger.info(
        f"SHOW-IMAGERY-TOOL: AOI: {aoi_names}, Target date: {target_date}"
    )

    request = ImageryRequest(
        aois=aois,
        target_date=parsed_date,
        language=language,
        window_days=window_days,
        max_cloud_cover=max_cloud_cover,
    )
    prefer_sentinel = provider is None and (
        parsed_date is None
        or PLANET_PROVIDER.is_newer_than_last_full_month(parsed_date)
    )
    if (
        provider != "sentinel-2"
        and not prefer_sentinel
        and PLANET_PROVIDER.covers(aois)
    ):
        return _provider_command(
            await PLANET_PROVIDER.get_imagery(request), tool_call_id
        )

    if provider == "planet":
        return _feedback(
            "Planet imagery is not available for this area and month. "
            "Sentinel-2 imagery is available instead.",
            tool_call_id,
        )

    result = await SENTINEL2_PROVIDER.get_imagery(request)
    if (
        result.status == "success"
        and provider is None
        and parsed_date is None
        and PLANET_PROVIDER.covers(aois)
    ):
        result = replace(
            result,
            message=(
                f"{result.message} Planet monthly imagery from the previous "
                "complete month is also available for this area."
            ),
        )
    return _provider_command(result, tool_call_id)


SPEC = ToolSpec(
    tool=show_imagery,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- show_imagery(provider, target_date): show Planet or Sentinel-2 "
        "imagery for the AOI in state. With no provider or date, Sentinel-2 "
        "covers approximately the previous two weeks. Run pick_aoi first."
    ),
)
