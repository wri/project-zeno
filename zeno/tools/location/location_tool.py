import os
from typing import Tuple

import fiona
import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

gadm = fiona.open("data/gadm_410_small.gpkg")


class LocationInput(BaseModel):
    """Input schema for location finder tool"""

    query: str = Field(
        description="Name of the location to search for. Can be a city, region, or country name."
    )


@tool(
    "location-tool",
    args_schema=LocationInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def location_tool(query: str) -> Tuple[list, list]:
    """Find locations and their administrative hierarchies given a place name.
      Returns a list of IDs with matches at different administrative levels

    Args:
        query (str): Location name to search for

    Returns:
        matches (Tuple[list, list]): GDAM feature IDs their geojson feature collections
    """
    print("---LOCATION-TOOL---")

    url = f"https://api.mapbox.com/search/geocode/v6/forward?q={query}&autocomplete=false&access_token={os.environ.get('MAPBOX_API_TOKEN')}"
    response = requests.get(url)

    aois = []
    for result in response.json()["features"]:
        lon = result["geometry"]["coordinates"][0]
        lat = result["geometry"]["coordinates"][1]
        print(result)
        for rowid, match in gadm.items(bbox=(lon, lat, lon, lat)):
            aois.append(match)
            break

    fids = [dat["properties"]["gadmid"] for dat in aois]

    geojson = {
        "type": "FeatureCollection",
        "features": [aoi.__geo_interface__ for aoi in aois],
    }

    return fids, geojson
