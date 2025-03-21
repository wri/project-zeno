import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Any

import fiona
import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator, field_validator
from shapely import simplify
from shapely.geometry import mapping, shape

data_dir = Path("data")
# Open GADM datasets
gadm_0 = fiona.open(data_dir / "gadm_410_level_0.gpkg")
gadm_1 = fiona.open(data_dir / "gadm_410_level_1.gpkg")
gadm_2 = fiona.open(data_dir / "gadm_410_level_2.gpkg")

GADM_BY_LEVEL = {0: gadm_0, 1: gadm_1, 2: gadm_2}


class LocationInput(BaseModel):
    """Input schema for location finder tool"""

    query: str = Field(
        description="Name of the location to search for. Can be a city, region, or country name."
    )


class RelativeLocationInput(BaseModel):

    gadm_level: int = Field(
        description="GADM level to search for. 0 for countries, 1 for regions, 2 for cities"
    )
    parent_gadm_id: Optional[str] = Field(
        description="GADM ID of the parent location to search for (if searching for children)",
        default=None,
    )
    parent_gadm_level: Optional[int] = Field(
        description="GADM level of the parent location to search for (if searching for children)",
        default=None,
    )

    # NOTE: this validation technically allows the query input to request
    # locations for GADM level 0 with a parent (even though parent level
    # 0 has no parents). In this case the parent at level 0 will be returned
    @model_validator(mode="after")
    def ensure_parent_id_and_level(self):

        if bool(self.parent_gadm_id) != bool(self.parent_gadm_level is not None):
            raise ValueError(
                "BOTH parent_gadm_level and parent_gadm_id are required in order to query for locations relative to a parent."
            )

        return self

    @model_validator(mode="after")
    def ensure_parent_if_gadm_level_not_0(self):

        if self.parent_gadm_id is None and self.gadm_level != 0:
            raise ValueError(
                "Only countries (GADM level 0) can be queried WITHOUT a parent GADM ID."
            )

        return self

    @field_validator("gadm_level", "parent_gadm_level", mode="after")
    def validate_level(cls, value):
        if value not in GADM_BY_LEVEL.keys():
            raise ValueError(
                f"Invalid GADM level: {value}. Must be one of {GADM_BY_LEVEL.keys()}"
            )
        return value


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
    simplified = simplify(geometry, tolerance=tolerance, preserve_topology=True)
    geojson_feature["geometry"] = mapping(simplified)
    return geojson_feature


def determine_gadm_level(place_type: str) -> Optional[int]:
    """Determine GADM level based on place type from Mapbox API."""

    # Level 1 types (larger administrative divisions)
    level_1_types = {"region", "state", "province", "territory"}

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

    if place_type.lower() == "country":
        return 0
    if place_type.lower() in level_1_types:
        return 1
    if place_type.lower() in level_2_types:
        return 2

    return 2


def process_single_location(
    coords: List[float], gadm_level: int
) -> Tuple[
    Optional[str], Optional[str], Optional[str], Optional[int], Optional[Dict[str, Any]]
]:
    """Process a single location's coordinates to find matching GADM feature."""
    lon, lat = coords
    # First, search for matches within the requested GADM level
    gadm = GADM_BY_LEVEL[gadm_level]
    matches = list(gadm.items(bbox=(lon, lat, lon, lat)))

    # If no matches found, try alternate level
    if not matches:

        for level in GADM_BY_LEVEL.keys():
            if level == gadm_level:
                continue
            gadm = GADM_BY_LEVEL[level]
            matches = list(gadm.items(bbox=(lon, lat, lon, lat)))
            if matches:
                gadm_level = level
                break

    if not matches:
        return (None, None, None, None, None)

    # Get the first match and convert to GeoJSON
    match = matches[0][1]
    geojson_feature = convert_to_geojson(match)

    # Get GADM ID
    gadm_id = match["properties"][f"GID_{gadm_level}"]

    name_key = f"NAME_{gadm_level}" if gadm_level != 0 else "COUNTRY"

    admin_level = (
        "Country"
        if gadm_level == 0
        else match["properties"].get(f"ENGTYPE_{gadm_level}", "Unknown")
    )

    simplified_feature = simplify_geometry(geojson_feature)
    simplified_feature["properties"] = {
        "gadm_id": gadm_id,
        "name": match["properties"][name_key],
        "gadm_level": gadm_level,
        "admin_level": admin_level,
    }

    return (
        match["properties"][name_key],
        admin_level,
        gadm_id,
        gadm_level,
        simplified_feature,
    )


@tool(
    "relative-location-tool",
    args_schema=RelativeLocationInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def relative_location_tool(
    gadm_level: int,
    parent_gadm_id: Optional[str] = None,
    parent_gadm_level: Optional[int] = None,
) -> Tuple[List[Tuple], List[Dict[str, Any]]]:
    """Returns a list of GADM Items for a requested GADM Level.
    Note that BOTH parent_gadm_level and parent_gadm_id are required in order to query for locations relative to a parent.
    """

    gadm = GADM_BY_LEVEL[gadm_level]

    matches = [
        m
        for m in gadm
        if (
            m["properties"][f"GID_{parent_gadm_level}"] == parent_gadm_id
            if parent_gadm_id
            else True
        )
    ]
    results = []
    for match in matches:
        gadm_id = match["properties"][f"GID_{gadm_level}"]
        name = match["properties"][
            f"NAME_{gadm_level}" if gadm_level != 0 else "COUNTRY"
        ]
        admin_level = (
            "Country"
            if gadm_level == 0
            else match["properties"].get(f"ENGTYPE_{gadm_level}", "Unknown")
        )

        geojson_feature = convert_to_geojson(match)
        simplified_feature = simplify_geometry(geojson_feature)

        simplified_feature["properties"] = {
            "gadm_id": gadm_id,
            "name": name,
            "admin_level": admin_level,
            "gadm_level": gadm_level,
        }
        results.append(((name, admin_level, gadm_id, gadm_level), simplified_feature))

    return [item[0] for item in results], [item[1] for item in results]


@tool(
    "location-tool",
    args_schema=LocationInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def location_tool(
    query: str,
) -> Tuple[List[Tuple], List[Dict[str, Any]]]:
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
        (name, admin_level, gadm_id, gadm_level, simplified_feature) = (
            process_single_location(feature["geometry"]["coordinates"], gadm_level)
        )

        if gadm_id and simplified_feature:
            # Add Mapbox metadata to help distinguish between results
            simplified_feature["properties"].update(
                {
                    "mapbox_place_name": feature["properties"].get("name", ""),
                    "mapbox_context": feature["properties"].get("context", {}),
                }
            )
            results.append(
                ((name, admin_level, gadm_id, gadm_level), simplified_feature)
            )

    return f"Pick one of the following options: {[item[0] for item in results]}", [
        item[1] for item in results
    ]
