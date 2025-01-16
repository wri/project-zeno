import os
from typing import Literal, Tuple

import fiona
import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

gadm_1 = fiona.open("data/gadm_410_level_1.gpkg")
gadm_2 = fiona.open("data/gadm_410_level_2.gpkg")


class LocationInput(BaseModel):
    """Input schema for location finder tool"""

    query: str = Field(
        description="Name of the location to search for. Can be a city, region, or country name."
    )
    gadm_level: Literal[1, 2] = Field(
        description="GADM level to use. The value 1 is for obtaining states or districts, 2 is for smaller areas like counties and municipalities"
    )


@tool(
    "location-tool",
    args_schema=LocationInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def location_tool(query: str, gadm_level: Literal[1, 2]) -> Tuple[list, list]:
    """Find locations and their administrative hierarchies given a place name.
      Returns a list of IDs with matches at different administrative levels.

    Args:
        query (str): Location name to search for
        gadm_level (Literal[1, 2]): Gadm level to use.

    Returns:
        matches (Tuple[list, list]): GDAM feature IDs their geojson feature collections
    """
    print("---LOCATION-TOOL---")
    print(f"Using GADM level {gadm_level}, location {query}")

    if gadm_level == 1:
        gadm = gadm_1
    elif gadm_level == 2:
        gadm = gadm_2

    url = f"https://api.mapbox.com/search/geocode/v6/forward?q={query}&autocomplete=false&limit=3&access_token={os.environ.get('MAPBOX_API_TOKEN')}"
    response = requests.get(url).json()

    print(f"Found {len(response['features'])} locations")

    aois = []
    fids = []
    for result in response["features"]:
        lon = result["geometry"]["coordinates"][0]
        lat = result["geometry"]["coordinates"][1]
        for _, match in gadm.items(bbox=(lon, lat, lon, lat)):
            fid = match["properties"][f"GID_{gadm_level}"]
            if fid in fids:
                continue
            match["properties"]["gadmid"] = fid
            match["properties"]["name"] = match["properties"][
                f"NAME_{gadm_level}"
            ]
            aois.append(match)
            fids.append(fid)
            if len(fids) == 3:
                break

    geojson = {
        "type": "FeatureCollection",
        "features": [aoi.__geo_interface__ for aoi in aois],
    }

    return fids, geojson
