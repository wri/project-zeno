from pathlib import Path
from typing import Annotated, Optional, List

import pandas as pd
import geopandas as gpd
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from thefuzz import process

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
    name: Optional[str] = None,
    gadm_id: Optional[str] = None,
    gadm_level: Optional[int] = None,
    kba_names: Optional[List[str]] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Finds data for Key Biodiversity Areas (KBAs) within an area of interest.

    Args:
        name: Name of the location to search for (optional).
        gadm_id: GADM ID of the location to search for (optional).
        gadm_level: GADM level of the location to search for (optional).
        kba_names: List of KBAs to search for (optional). If provided, only data for these KBAs will be returned.
    """
    print("kba data tool")

    if kba_names:
        # fuzzy match over kba names
        result = []
        for kba_name in kba_names:
            *_, index = process.extractOne(kba_name, kba.siteName)
            result.append(kba.iloc[index])
        kba_within_aoi = gpd.GeoDataFrame(result, geometry="geometry")
        data = f"Found KBAs: {kba_within_aoi.siteName.to_list()}"
    else:
        aoi = get_aoi(gadm_id=gadm_id, gadm_level=gadm_level)
        kba_within_aoi = kba[kba.geometry.within(aoi)]
        data = f"Found data for {len(kba_within_aoi)} KBAs within the area of interest: {name}."
    return Command(
        update={
            "kba_within_aoi": kba_within_aoi.to_json(),
            "messages": [
                ToolMessage(
                    content=data,
                    # artifact=kba_within_aoi.to_json(), # Issue with streamlit render on front-end, premature stop of stream
                    tool_call_id=tool_call_id,
                )
            ],
        },
        goto="kba_node",
    )
