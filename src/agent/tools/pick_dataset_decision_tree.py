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
    all = "all"
    natural_land = "natural_land"
    forest = "forest"
    primary_forest = "primary_forest"
    grasslands = "grasslands"
    croplands = "croplands"
    wetland = "wetland"
    peatland = "peatland"
    mangrove = "mangrove"
    natural_forest = "natural_forest"
    short_vegetation = "short_vegetation"
    built_up = "built_up"


class Event(str, Enum):
    loss = "loss"
    gain = "gain"
    change = "change"
    disturbance = "disturbance"
    carbon_emission = "carbon_emission"
    carbon_removal = "carbon_removal"
    deforestation = "deforestation"


class Cause(str, Enum):
    all = "all"
    wildfire = "wildfire"
    agriculture = "agriculture"
    logging = "logging"
    settlements = "settlements"
    crop_management = "crop_management"


class Measurement(str, Enum):
    area = "area"
    co2e = "co2e"
    co2 = "co2"
    net_flux = "net_flux"


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
    event: Optional[Event] = None,
    cause: Optional[Cause] = None,
    measurement: Optional[Measurement] = None,
    definition: Optional[Definition] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    temporal_resolution: Optional[TemporalResolution] = None,
) -> Command:
    """
    Picks the appropriate dataset based on structured parameters derived from the user query.
    Set each parameter to the best matching value, or null if not relevant.

    Args:
        land_cover: The primary land cover the user is asking about.
            Use `forest` for general forest questions, `primary_forest` for old-growth or intact forest.
            Use `natural_land` for broad natural ecosystem questions. Use `grasslands` for grassland-specific
            questions. Use `wetland`, `peatland`, or `mangrove` when the user names those ecosystems.
        event: The type of change or phenomenon the user is asking about.
            Use `loss` for deforestation or cover loss. Use `gain` for reforestation or cover gain.
            Use `disturbance` for alerts or ecosystem disruptions. Use `change` when the user asks about
            land cover transitions (e.g. "what changed from X to Y"). Use `net_flux` for source/sink or
            net emissions questions.
        cause: Set only when the user specifies what drove the event (e.g. wildfire, agriculture, logging,
            settlements, crop management). Set to `any` if user is asking broadly about causes, or leave null if cause isn't mentioned.
        measurement: What the user wants to quantify. Use `area` for extent, coverage, or hectares — this
            is the default when the user asks about loss, gain, or disturbance without specifying a unit.
            Use `co2` or `co2e` when the user asks about emissions or carbon released. Use `net_flux` when
            the user asks about net carbon balance, whether a place is a source or sink, or net GHG flux.
        definition: Set `forest_canopy_cover` when the user specifies a canopy density threshold
            (e.g. "using a 30% canopy cover threshold").
        start_date: Start date in YYYY-MM-DD format, parsed from the user query.
        end_date: End date in YYYY-MM-DD format, parsed from the user query.
        temporal_resolution: Set when the user asks for monthly, annual, or aggregated data. Leave null
            if not specified.
    """
    logger.info("PICK-DATASET-DECISION-TREE-TOOL")

    dataset_id = choose_dataset(land_cover, event, cause, measurement)

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
            return 0, None
        else:
            return 1, None
    elif land_cover == LandCover.forest:
        if event == event.loss:
            return 1
        elif event == event.deforestation:
            return 1, "primary_forest"
