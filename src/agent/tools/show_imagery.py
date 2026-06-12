from datetime import date
from typing import Annotated, Dict, Optional

import structlog
from cogeo_mosaic.errors import MosaicNotFoundError
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.api.services.mosaic import (
    AoiTooLargeError,
    MosaicRecipe,
    NoScenesFoundError,
    StacSearchError,
    create_sentinel2_mosaic,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


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


@tool("show_imagery")
async def show_imagery(
    state: Annotated[Dict, InjectedState],
    target_date: Optional[str] = None,
    window_days: Optional[int] = None,
    max_cloud_cover: Optional[int] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Show a Sentinel-2 satellite imagery layer on the map for the AOI in state.

    target_date (YYYY-MM-DD) picks the date the imagery should be closest
    to; defaults to today. window_days (default 7, max 183) widens the
    search to ±N days around target_date; max_cloud_cover (default 20,
    percent) loosens the cloud filter. Only raise them when the defaults
    find no scenes and the user agrees. Run pick_aoi first. Regional
    areas only.
    """
    aois = (state.get("aoi_selection") or {}).get("aois") or []
    if not aois:
        return _feedback(
            "No AOI selected. Run pick_aoi before requesting satellite imagery.",
            tool_call_id,
        )

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            return _feedback(
                f"Invalid target_date '{target_date}'. Use YYYY-MM-DD.",
                tool_call_id,
            )

    aoi_names = [a["name"] for a in aois]
    logger.info(
        f"SHOW-IMAGERY-TOOL: AOI: {aoi_names}, Target date: {target_date}"
    )

    aoi_refs = tuple((a["source"], a["src_id"]) for a in aois)
    user_id = None
    if any(source == "custom" for source, _ in aoi_refs):
        user_id = structlog.contextvars.get_contextvars().get("user_id")

    recipe = MosaicRecipe(
        aois=aoi_refs,
        target_date=parsed_date or date.today(),
        window_days=max(1, min(window_days, 183))
        if window_days is not None
        else 7,
        max_cloud_cover=max(1, min(max_cloud_cover, 100))
        if max_cloud_cover is not None
        else 20,
        user_id=user_id,
    )

    try:
        result = await create_sentinel2_mosaic(recipe)
    except MosaicNotFoundError:
        return _feedback(
            "Could not load the geometry of the selected AOI.", tool_call_id
        )
    except AoiTooLargeError as e:
        return _feedback(str(e), tool_call_id)
    except NoScenesFoundError:
        return _feedback(
            f"No Sentinel-2 scenes with under {recipe.max_cloud_cover}% "
            f"cloud cover found within ±{recipe.window_days} days of "
            f"{recipe.target_date}. Suggest to the user: widen the search "
            "window (window_days), allow cloudier scenes (max_cloud_cover) "
            "or pick a different date — then retry with their choice.",
            tool_call_id,
        )
    except StacSearchError:
        return _feedback(
            "The Sentinel-2 catalog is currently unavailable. Try again later.",
            tool_call_id,
        )

    imagery = {
        "tile_url": result.tile_url,
        "tilejson_url": result.tilejson_url,
        "mosaic_id": result.mosaic_id,
        "item_count": result.item_count,
        "date_start": result.date_start.isoformat(),
        "date_end": result.date_end.isoformat(),
        "target_date": recipe.target_date.isoformat(),
        "window_days": recipe.window_days,
        "max_cloud_cover": recipe.max_cloud_cover,
        "aoi_names": aoi_names,
    }

    return Command(
        update={
            "imagery": imagery,
            "messages": [
                ToolMessage(
                    f"Sentinel-2 imagery layer created for {', '.join(aoi_names)} "
                    f"from {result.item_count} scenes acquired between "
                    f"{result.date_start} and {result.date_end}. "
                    "The layer is shown on the map.",
                    tool_call_id=tool_call_id,
                )
            ],
        },
    )
