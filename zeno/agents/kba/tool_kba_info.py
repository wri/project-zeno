from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import geopandas as gpd
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from shapely.geometry import shape

from zeno.agents.distalert.tool_location import location_tool

data_dir = Path("data/kba")
kba = gpd.read_file(data_dir / "kba_data_preparation/kba_merged.gpkg")


class KbaInfoInput(BaseModel):
    query: str = Field(
        ...,
        description="Name of the location to search for. Can be a city, region, or country name.",
    )
    columns: List[str] = Field(
        ...,
        description="List of column names relevant to the user query",
    )


@tool(
    "kba-info-tool",
    args_schema=KbaInfoInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def kba_info_tool(
    query: str,
    columns: List[str],
) -> List[Tuple[Optional[str], Optional[Dict[str, Any]]]]:
    """
    Finds location of all Key Biodiversity Areas (KBAs) with in an area of interest.
    """
    print("kba info tool")
    result = location_tool.invoke(
        {
            "name": "location-tool",
            "args": {
                "query": query,
            },
            "id": str(uuid4()),
            "type": "tool_call",
        }
    )  # pass a tool call to return the artifact
    _, artifact = result.content, result.artifact
    aoi_geometry = shape(artifact[0]["geometry"])
    aoi_buffered = aoi_geometry.buffer(0.1)

    kba_within_aoi = kba[kba.geometry.within(aoi_buffered)]

    # make sure to have siteName, sitecode in the columns if they are not in the columns list
    if "siteName" not in columns:
        columns.append("siteName")
    if "sitecode" not in columns:
        columns.append("sitecode")
    # remove geometry column if it is in the columns list
    if "geometry" in columns:
        columns.remove("geometry")

    # filter columns
    kba_within_aoi_filtered = kba_within_aoi[columns]
    kba_within_aoi_geometry = kba_within_aoi[["sitecode", "geometry"]]

    return (
        kba_within_aoi_filtered.to_csv(index=False),
        kba_within_aoi_geometry.to_json(),
    )
