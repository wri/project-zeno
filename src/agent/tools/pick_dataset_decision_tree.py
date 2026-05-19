from enum import Enum
from typing import Annotated, Dict, List, Optional

from langchain.tools import InjectedState
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command


class LandCover(str, Enum):
    land = "land"
    forest = "forest"
    primary_forest = "primary_forest"
    grasslands = "grasslands"
    croplands = "croplands"


class LandUse(str, Enum):
    pass


class Event(str, Enum):
    loss = "loss"
    gain = "gain"
    transition = "transition"
    disturbance = "disturbance"


class Cause(str, Enum):
    wildfire = "wildfire"


class Measurement(str, Enum):
    area = "area"
    co2e = "co2e"
    co2 = "co2"


@tool("pick_dataset_decision_tree")
async def pick_dataset_decision_tree(
    state: Annotated[Dict, InjectedState],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
    land_cover: Optional[List[LandCover]] = None,
    land_use: Optional[List[LandUse]] = None,
    event: Optional[List[Event]] = None,
    cause: Optional[List[Cause]] = None,
    measurement: Optional[List[Measurement]] = None,
) -> Command:
    """
    Selects a dataset using a decision tree based on structured parameters
    rather than LLM-based retrieval.

    Args:
        land_cover: The land cover type
        land_use: The land use type
        event: The type of event or change that occurred
        cause: What caused the event
        measurement: The data to collect (e.g. area, carbon)
    """
    
    dataset_choice = choose_dataset(land_cover, land_use, event, cause, measurement)
    pass


def choose_dataset(land_cover, land_use, event, cause, measurement):
    return 4
