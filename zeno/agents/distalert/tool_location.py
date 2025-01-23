import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fiona
import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from shapely import simplify
from shapely.geometry import mapping, shape

data_dir = Path("data")
# Open GADM datasets
gadm_1 = fiona.open(data_dir / "gadm_410_level_1.gpkg")
gadm_2 = fiona.open(data_dir / "gadm_410_level_2.gpkg")


class LocationInput(BaseModel):
    """Input schema for location finder tool"""

    query: str = Field(
        description="Name of the location to search for. Can be a city, region, or country name."
    )


def convert_to_geojson(fiona_feature: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Fiona Feature to a GeoJSON Feature."""
    return {
        "type": "Feature",
        "geometry": fiona_feature["geometry"],
        "properties": fiona_feature["properties"],
    }


def simplify_geometry(
    geojson_feature: Dict[str, Any], tolerance: float = 0.001
) -> Dict[str, Any]:
    """Simplify a GeoJSON feature's geometry while preserving topology."""
    geometry = shape(geojson_feature["geometry"])
    simplified = simplify(
        geometry, tolerance=tolerance, preserve_topology=True
    )
    geojson_feature["geometry"] = mapping(simplified)
    return geojson_feature


def determine_gadm_level(place_type: str) -> Optional[int]:
    """Determine GADM level based on place type from Mapbox API."""
    # Level 2 types (more specific locations)
    level_2_types = {
        "place",
        "district",
        "municipality",
        "city",
        "town",
        "village",
        "county",
        "borough",
        "locality",
    }
    # Level 1 types (larger administrative divisions)
    level_1_types = {"region", "state", "province", "territory", "country"}

    if place_type.lower() in level_2_types:
        return 2
    elif place_type.lower() in level_1_types:
        return 1
    return 2


def process_single_location(
    coords: List[float], gadm_level: int
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Process a single location's coordinates to find matching GADM feature."""
    lon, lat = coords
    gadm = gadm_2 if gadm_level == 2 else gadm_1

    # Find matching GADM feature
    matches = list(gadm.items(bbox=(lon, lat, lon, lat)))
    if not matches:
        # Try alternate level if no matches found
        alternate_level = 1 if gadm_level == 2 else 2
        gadm = gadm_1 if alternate_level == 1 else gadm_2
        matches = list(gadm.items(bbox=(lon, lat, lon, lat)))
        if matches:
            gadm_level = alternate_level

    if not matches:
        return None, None

    # Get the first match and convert to GeoJSON
    match = matches[0][1]
    geojson_feature = convert_to_geojson(match)

    # Get GADM ID
    gadm_id = match["properties"][f"GID_{gadm_level}"]

    # Simplify geometry and prepare response
    simplified_feature = simplify_geometry(geojson_feature)
    simplified_feature["properties"] = {
        "gadm_id": gadm_id,
        "name": match["properties"][f"NAME_{gadm_level}"],
        "gadm_level": gadm_level,
        "admin_level": match["properties"].get(
            f"ENGTYPE_{gadm_level}", "Unknown"
        ),
    }

    return (
        match["properties"][f"NAME_{gadm_level}"],
        gadm_id,
        gadm_level,
        simplified_feature,
    )


@tool(
    "location-tool",
    args_schema=LocationInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def location_tool(
    query: str,
) -> List[Tuple[Optional[str], Optional[Dict[str, Any]]]]:
    """
    Finds top 3 matches for a location name and returns their name, gadm_id & gadm_level.
    """
    # Query Mapbox API with limit=3
    url = f"https://api.mapbox.com/search/geocode/v6/forward?q={query}&autocomplete=false&limit=3&access_token={os.environ.get('MAPBOX_API_TOKEN')}"
    response = requests.get(url)

    if not response.ok:
        raise ValueError(f"Geocoding failed: {response.status_code}")

    data = response.json()
    if not data.get("features"):
        raise ValueError(f"No locations found for query: {query}")

    results = []
    for feature in data["features"]:
        place_type = feature["properties"].get("feature_type", None)
        gadm_level = determine_gadm_level(place_type)

        # Process the location
        name, gadm_id, gadm_level, simplified_feature = (
            process_single_location(
                feature["geometry"]["coordinates"], gadm_level
            )
        )

        if gadm_id and simplified_feature:
            # Add Mapbox metadata to help distinguish between results
            simplified_feature["properties"].update(
                {
                    "mapbox_place_name": feature["properties"].get("name", ""),
                    "mapbox_context": feature["properties"].get("context", {}),
                }
            )
            results.append(((name, gadm_id, gadm_level), simplified_feature))

    return [item[0] for item in results], [item[1] for item in results]
