from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.tools.location.location_matcher import LocationMatcher

GADM_CSV_PATH = "data/gadm.csv"
location_matcher = LocationMatcher(GADM_CSV_PATH)

class LocationInput(BaseModel):
    """Input schema for location finder tool"""
    query: str = Field(
        description="Name of the location to search for. Can be a city, region, or country name."
    )
    threshold: int = Field(
        default=70,
        description="Minimum similarity score (0-100) to consider a match. Default is 70.",
        ge=0,
        le=100
    )


@tool("location-tool", args_schema=LocationInput, return_direct=True)
def location_tool(query: str, threshold: int = 70) -> dict:
    """Find locations and their administrative hierarchies given a place name.
      Returns matches at different administrative levels (ADM2, ADM1, ISO) with their IDs and names.

    Args:
        query (str): Location name to search for
        threshold (int, optional): Minimum similarity score. Defaults to 70.

    Returns:
        dict: matching locations
    """
    try:
        matches = location_matcher.find_matches(query, threshold=threshold)
        return matches
    except Exception as e:
        return f"Error finding locations: {str(e)}"
