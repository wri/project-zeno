from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Annotated
from uuid import uuid4

import geopandas as gpd
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from shapely.geometry import shape
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from zeno.agents.distalert.tool_location import location_tool

data_dir = Path("data/kba")
kba = gpd.read_file(data_dir / "kba_merged.gpkg")

@tool("kba-data-tool")
def kba_data_tool(
    query: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    config: RunnableConfig
) -> Command:
    """
    Finds location of all Key Biodiversity Areas (KBAs) with in an area of interest.

    Args:
        query: Name of the location to search for. Can be a city, region, or country name.
    """
    print("kba data tool")
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
    aoi_buffered = aoi_geometry.buffer(0.1) # 0.1 degree buffer i.e ~11km

    kba_within_aoi = kba[kba.geometry.within(aoi_buffered)]

    data = f"Found data for {len(kba_within_aoi)} KBAs within the area of interest: {query}."
    return Command(
        update={
            "kba_within_aoi": kba_within_aoi.to_json(),
            "messages": [ToolMessage(content=data, tool_call_id=tool_call_id)],
        },
    )
