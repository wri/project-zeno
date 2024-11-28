from typing import List

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from zeno.tools.location.location_matcher import LocationMatcher

location_matcher = LocationMatcher("data/gadm41_PRT.gpkg")


class LocationInput(BaseModel):
    """Input schema for location finder tool"""

    query: str = Field(
        description="Name of the location to search for. Can be a city, region, or country name."
    )


@tool("location-tool", args_schema=LocationInput, return_direct=False)
def location_tool(query: str) -> List[str]:
    """Find locations and their administrative hierarchies given a place name.
      Returns a list of IDs with matches at different administrative levels

    Args:
        query (str): Location name to search for

    Returns:
        matches (List[str]): ids of matching locations
    """
    print("---LOCATION-TOOL---")
    try:
        matches = location_matcher.find_matches(query)
        return matches
    except Exception as e:
        return f"Error finding locations: {str(e)}"
