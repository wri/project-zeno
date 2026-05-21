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


class LandUse(str, Enum):
    built_up = "built_up"                          # urban, development, settlements, infrastructure
    cropland = "cropland"                          # agriculture, crops, farming
    cultivated_grassland = "cultivated_grassland"  # cultivated pasture
    tree_cover = "tree_cover"                      # forest, woodland
    short_vegetation = "short_vegetation"          # shrubland, savanna, non-cultivated grassland
    wetland = "wetland"                            # marshes, swamps
    water = "water"                                # rivers, lakes
    bare_ground = "bare_ground"                    # sparse vegetation, desert


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


@tool("pick_land_change_dataset")
async def pick_land_change_dataset(
    state: Annotated[Dict, InjectedState],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
    land_cover: LandCover = LandCover.all,
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
    Picks the appropriate dataset based on structured parameters derived from the user query.
    Set each parameter to the best matching value, or null if not relevant.

    Args:
        land_cover: The primary land cover the user is asking about.
            Use `forest` for general forest questions, `primary_forest` for old-growth or intact forest.
            Use `natural_land` for broad natural ecosystem questions. Use `grasslands` for grassland-specific
            questions. Use `wetland`, `peatland`, or `mangrove` when the user names those ecosystems.
        land_use: The type of land use or land cover class the user is asking about, especially when
            asking about a specific land use category (e.g. built-up, cropland) or land cover/use change.
            Set this when the question is about a specific land use type regardless of whether a transition
            is involved. Use `built_up` for urban, development, settlements, or infrastructure questions.
            Use `cropland` for agriculture or farming. Do NOT set this for drivers of forest loss — use
            `cause` for that instead.
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

    result = choose_dataset(land_cover, land_use, event, cause, measurement, temporal_resolution)

    if result is None:
        raise ValueError(
            "No dataset is available for the combination of parameters provided. "
            "The requested land cover, event, or measurement may not be supported together."
        )

    dataset_id, context_layer, fallback_note = result

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
        context_layer=context_layer,
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

    tool_message = f"""{"# Note\n    " + fallback_note + "\n\n    " if fallback_note else ""}# About the selection
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


# Temporal resolutions supported per dataset (not in YAMLs, hardcoded from content_date)
_DATASET_TEMPORAL_RESOLUTIONS: dict[int, set[TemporalResolution]] = {
    0: {TemporalResolution.daily, TemporalResolution.monthly},  # DIST-ALERT
    1: {TemporalResolution.annual},                              # Global land cover
    2: {TemporalResolution.annual},                              # Grasslands
    3: {TemporalResolution.aggregate},                           # SBTN (2020 snapshot)
    4: {TemporalResolution.annual},                              # Tree cover loss
    5: {TemporalResolution.aggregate},                           # Tree cover gain (5-yr intervals)
    6: {TemporalResolution.annual},                              # Forest GHG net flux
    7: {TemporalResolution.aggregate},                           # Tree cover (2000 snapshot)
    8: {TemporalResolution.annual},                              # TCL by dominant driver
}

_FOREST_LAND_COVERS = (LandCover.forest, LandCover.primary_forest)
_NATURAL_LAND_COVERS = (LandCover.natural_land, LandCover.natural_forest,
                        LandCover.wetland, LandCover.peatland, LandCover.mangrove)
_GENERAL_LAND_COVERS = (LandCover.all, LandCover.croplands, LandCover.short_vegetation,
                        LandCover.built_up, LandCover.wetland, LandCover.peatland,
                        LandCover.mangrove, LandCover.natural_land)
_CARBON_MEASUREMENTS = (Measurement.co2, Measurement.co2e, Measurement.net_flux)


_FOREST_OR_ALL = _FOREST_LAND_COVERS + (LandCover.all,)
_DATASET_NAMES = {ds["dataset_id"]: ds["dataset_name"] for ds in DATASETS}


def choose_dataset(
    land_cover: LandCover,
    land_use,
    event,
    cause,
    measurement,
    temporal_resolution,
) -> tuple[int, str | None, str | None] | None:
    """Returns (dataset_id, context_layer, note) or None if no dataset matches.

    Decision tree: land_cover → event → cause → measurement → temporal_resolution.
    land_cover always provides a default; each subsequent level refines only when a
    more specific dataset exists for that combination.
    """
    note = None

    # Level 1: land_cover → default dataset
    if land_cover in _FOREST_LAND_COVERS:
        dataset_id = 7  # tree cover (static 2000)
        context_layer = "primary_forest" if land_cover == LandCover.primary_forest else None
    elif land_cover == LandCover.grasslands:
        dataset_id = 2  # natural/semi-natural grasslands
        context_layer = None
    elif land_cover in _NATURAL_LAND_COVERS:
        dataset_id = 3  # SBTN natural lands
        context_layer = None
    else:  # all, croplands, built_up, short_vegetation
        dataset_id = 1  # global land cover
        context_layer = None

    # Level 2: measurement — carbon always overrides to GHG flux
    if measurement in _CARBON_MEASUREMENTS or event in (Event.carbon_emission, Event.carbon_removal):
        dataset_id = 6
        context_layer = None
        if land_cover not in _FOREST_OR_ALL:
            note = f"No carbon data for {land_cover.value}; showing Forest GHG Net Flux"

    # Level 2: event → refine if a better dataset exists for this land_cover + event
    elif event == Event.disturbance:
        dataset_id = 0
        context_layer = "driver" if cause is not None else None
    elif event == Event.gain:
        if land_cover in _FOREST_OR_ALL:
            dataset_id = 5
        else:
            note = f"No gain data for {land_cover.value}; showing {_DATASET_NAMES.get(dataset_id, 'closest dataset')}"
    elif event in (Event.loss, Event.deforestation):
        if land_cover in _FOREST_OR_ALL:
            # Level 3: cause → refine
            if cause is not None:
                dataset_id = 8
                context_layer = "driver"
            else:
                dataset_id = 4
                context_layer = "primary_forest" if (event == Event.deforestation or land_cover == LandCover.primary_forest) else None
        elif land_use is not None:
            dataset_id = 1  # land use change question
        else:
            note = f"No {event.value} data for {land_cover.value}; showing {_DATASET_NAMES.get(dataset_id, 'closest dataset')}"

    elif event == Event.change:
        if land_cover != LandCover.grasslands:
            dataset_id = 1  # grasslands already at 2; everything else → land cover change
        context_layer = None

    # land_use without event → land cover change question
    elif land_use is not None:
        dataset_id = 1

    # Level 4: temporal_resolution — return None so caller raises (no further fallback)
    if temporal_resolution is not None:
        supported = _DATASET_TEMPORAL_RESOLUTIONS.get(dataset_id, set())
        if temporal_resolution not in supported:
            return None

    return dataset_id, context_layer, note