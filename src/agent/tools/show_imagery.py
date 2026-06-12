from datetime import date
from typing import Annotated, Dict, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from shapely import union_all
from shapely.geometry import mapping, shape

from src.api.services.mosaic import (
    AoiTooLargeError,
    NoScenesFoundError,
    StacSearchError,
    create_sentinel2_mosaic,
)
from src.shared.geocoding_helpers import get_geometry_data
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
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Show a Sentinel-2 satellite imagery layer on the map for the AOI in state.

    target_date (YYYY-MM-DD) picks the date the imagery should be closest
    to; defaults to today. Run pick_aoi first. Regional areas only.
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

    shapes = []
    for aoi in aois:
        data = await get_geometry_data(aoi["source"], aoi["src_id"])
        if data and data.get("geometry"):
            shapes.append(shape(data["geometry"]))
    if not shapes:
        return _feedback(
            "Could not load the geometry of the selected AOI.", tool_call_id
        )
    geometry = mapping(union_all(shapes))

    try:
        result = await create_sentinel2_mosaic(
            geometry=geometry, target_date=parsed_date
        )
    except AoiTooLargeError as e:
        return _feedback(str(e), tool_call_id)
    except NoScenesFoundError:
        return _feedback(
            "No cloud-free Sentinel-2 scenes found for this AOI around "
            f"{parsed_date or date.today()}. Try a different date.",
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
        "target_date": (parsed_date or date.today()).isoformat(),
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
