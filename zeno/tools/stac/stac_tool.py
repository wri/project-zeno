import datetime
from pathlib import Path
from typing import Tuple

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from pystac_client import Client
import geopandas as gpd

# Defaults to E84 AWS STAC catalog & Sentinel-2 L2A collection
CATALOG = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
data_dir = Path("data")


class StacInput(BaseModel):
    """Input schema for STAC search tool"""

    name: str = Field(description="Name of the area of interest")
    gadm_id: str = Field(description="GADM ID of the area of interest")
    gadm_level: int = Field(description="GADM level of the area of interest")
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
    name: str,
    gadm_id: str,
    gadm_level: int,
    min_date: datetime.datetime,
    max_date: datetime.datetime,
) -> dict:
    """Returns satellite images for a given area of interest."""
    print("---STAC-TOOL---")

    aoi_df = gpd.read_file(
        data_dir / f"gadm_410_level_{gadm_level}.gpkg",
        where=f"GID_{gadm_level} like '{gadm_id}'",
    )
    aoi = aoi_df.iloc[0]

    catalog = Client.open(CATALOG)

    query = catalog.search(
        collections=[COLLECTION],
        datetime=[min_date, max_date],
        max_items=10,
        intersects=aoi.geometry,
    )

    items = list(query.items())
    print(f"Found: {len(items):d} recent STAC items")

    # Convert STAC items into a GeoJSON FeatureCollection
    stac_json = query.item_collection_as_dict()
    stac_ids = [item.id for item in items]

    return stac_ids, stac_json
