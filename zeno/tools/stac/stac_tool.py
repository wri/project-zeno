import datetime
from typing import Tuple

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from pystac_client import Client


class StacInput(BaseModel):
    """Input schema for STAC search tool"""

    catalog: str = Field(
        description="STAC catalog to use for search",
        default="https://earth-search.aws.element84.com/v1",
    )
    collection: str = Field(
        description="STAC Clollection to use", default="sentinel-2-l2a"
    )
    bbox: Tuple[float, float, float, float] = Field(
        description="Bounding box for STAC search."
    )
    min_date: datetime.datetime = Field(
        description="Earliest date for retrieving STAC items.",
    )
    max_date: datetime.datetime = Field(
        description="Latest date for retrieving STAC items",
    )


@tool(
    "stac-tool",
    args_schema=StacInput,
    response_format="content_and_artifact",
)
def stac_tool(
    bbox: Tuple[float, float, float, float],
    min_date: datetime.datetime,
    max_date: datetime.datetime,
    catalog: str = "https://earth-search.aws.element84.com/v1",
    collection: str = "sentinel-2-l2a",
) -> dict:
    """Find locations and their administrative hierarchies given a place name.
    Returns a list of IDs with matches at different administrative levels
    """
    print("---SENTINEL-TOOL---")

    catalog = Client.open(catalog)

    query = catalog.search(
        collections=[collection],
        datetime=[min_date, max_date],
        max_items=10,
        bbox=bbox,
    )

    items = list(query.items())
    print(f"Found: {len(items):d} datasets")

    # Convert STAC items into a GeoJSON FeatureCollection
    stac_json = query.item_collection_as_dict()
    stac_ids = [item.id for item in items]

    return stac_ids, stac_json
