from enum import Enum
from typing import Annotated, Dict, List, Optional

from pydantic import BaseModel, Field

from langchain.tools import InjectedState
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command

from src.agent.tools.datasets_config import DATASETS
from src.agent.tools.pick_dataset.schema import DatasetSelectionResult
from src.agent.tools.util import revise_date_range
from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)



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
    change = "change"
    disturbance = "disturbance"


class Cause(str, Enum):
    wildfire = "wildfire"


class Measurement(str, Enum):
    area = "area"
    co2e = "co2e"
    co2 = "co2"


class TemporalResolution(str, Enum):
    aggregate = "aggregate"
    annual = "annual"
    monthly = "monthly"
    daily = "daily"


class Definition(BaseModel):
    forest_canopy_cover: Optional[int] = Field(None, description="Canopy cover density percent from 0-100 per 30m pixel", min=0, max=100)


    
@tool("pick_dataset_decision_tree")
async def pick_dataset_decision_tree(
    state: Annotated[Dict, InjectedState],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
    land_cover: Optional[LandCover] = None,
    land_use: Optional[LandUse] = None,
    event: Optional[Event] = None,
    cause: Optional[Cause] = None,
    measurement: Optional[Measurement] = None,
    definition: Optional[Definition] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    temporal_resolution: Optional[TemporalResolution] = None,
) -> Command:
    """
    Picks the appropriate dataset based on the below parameters. Pick the best fit option
    for each parameter, or pass null if the parameter isn't relevant to the user query.

    Args:
        land_cover: The land cover type
        land_use: The land use type
        event: The type of event or change that occurred
        cause: What caused the event
        measurement: The data to collect (e.g. area, carbon)
        definition: additional definitions to define LULC
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        temporal_resolution: The temporal resolution of the data
    """
    logger.info("PICK-DATASET-DECISION-TREE-TOOL")

    dataset_id = choose_dataset(land_cover, land_use, event, cause, measurement)

    row = next((ds for ds in DATASETS if ds["dataset_id"] == dataset_id), None)
    if row is None:
        raise ValueError(f"choose_dataset returned unknown dataset_id: {dataset_id}")

    tile_url = row["tile_url"]
    if tile_url and not tile_url.startswith("http"):
        tile_url = SharedSettings.eoapi_base_url + tile_url

    start_date, end_date, _ = await revise_date_range(start_date, end_date, dataset_id, None)

    result = DatasetSelectionResult(
        dataset_id=dataset_id,
        dataset_name=row["dataset_name"],
        context_layer=None,
        context_layers=[],
        parameters=None,
        start_date=start_date,
        end_date=end_date,
        reason="Selected by decision tree",
        tile_url=tile_url,
        analytics_api_endpoint=row["analytics_api_endpoint"],
        description=row["description"],
        prompt_instructions=row.get("prompt_instructions", ""),
        methodology=row.get("methodology", ""),
        cautions=row.get("cautions", ""),
        function_usage_notes=row.get("function_usage_notes", ""),
        citation=row.get("citation", ""),
        content_date=row.get("content_date", ""),
        selection_hints=row.get("selection_hints"),
        code_instructions=row.get("code_instructions"),
        presentation_instructions=row.get("presentation_instructions"),
    )

    tool_message = f"""# About the selection
    Selected dataset name: {result.dataset_name}
    Selected context layer: {result.context_layer}
    Reasoning for selection: {result.reason}

    # Additional dataset information

    ## Description

    {result.description}

    ## Function usage notes:

    {result.function_usage_notes}

    ## Usage cautions

    {result.cautions}

    ## Content date

    {result.content_date}
    """

    return Command(
        update={
            "dataset": result.model_dump(),
            "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
        },
    )


def choose_dataset(land_cover, land_use, event, cause, measurement, start_date, end_date, temporal_resolution):
    if land_cover is None:
        if start_date > "2023-01-01":
            return 0
        else:
            return 1
