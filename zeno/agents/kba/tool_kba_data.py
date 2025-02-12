from pathlib import Path
from typing import Annotated

import geopandas as gpd
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command

data_dir = Path("data/kba")
kba = gpd.read_file(data_dir / "kba_merged.gpkg")


def get_aoi(gadm_id: str, gadm_level: int, buffer_distance: float = 0.1):
    aoi_df = gpd.read_file(
        Path("data") / f"gadm_410_level_{gadm_level}.gpkg",
        where=f"GID_{gadm_level} like '{gadm_id}'",
    )
    aoi = aoi_df.geometry.iloc[0]

    if buffer_distance:
        aoi = aoi.buffer(buffer_distance)

    return aoi


@tool("kba-data-tool")
def kba_data_tool(
    name: str,
    gadm_id: str,
    gadm_level: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Finds location of all Key Biodiversity Areas (KBAs) with in an area of interest.

    Args:
        name: Name of the location to search for. Can be a city, region, or country name.
        gadm_id: GADM ID of the location to search for.
        gadm_level: GADM level of the location to search for.
    """
    print("kba data tool")
    aoi = get_aoi(gadm_id=gadm_id, gadm_level=gadm_level)

    kba_within_aoi = kba[kba.geometry.within(aoi)]

    data = f"Found data for {len(kba_within_aoi)} KBAs within the area of interest: {name}."
    return Command(
        update={
            "kba_within_aoi": kba_within_aoi.to_json(),
            "messages": [ToolMessage(content=data, tool_call_id=tool_call_id)],
        },
    )
