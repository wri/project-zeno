from enum import Enum
from types import SimpleNamespace
from typing import Annotated, Dict, List, Optional

from pydantic import BaseModel, Field

from langchain.tools import InjectedState
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command

from src.agent.tools.datasets_config import DATASETS
from src.agent.tools.pick_dataset.schema import DatasetSelectionResult
from src.agent.tools.pick_dataset.tool import get_tile_services_for_dataset
from src.agent.tools.util import revise_date_range
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class LandUseLandCover(str, Enum):
    all = "all"
    natural_land = "natural land"
    forest = "forest"
    primary_forest = "primary forest"
    grasslands = "grasslands"
    cropland = "cropland"
    wetland = "wetland"
    peatland = "peatland"
    mangrove = "mangrove"
    natural_forest = "natural forest"
    short_vegetation = "short vegetation"
    cultivated_grassland = "cultivated grassland"
    built_up = "built-up land"
    water = "water"
    bare_ground = "bare ground"


class Event(str, Enum):
    loss = "loss"
    gain = "gain"
    change = "change"
    disturbance = "disturbance"
    carbon_emission = "carbon_emission"
    carbon_removal = "carbon_removal"
    deforestation = "deforestation"


class Cause(str, Enum):
    all = "any cause"
    wildfire = "wildfire"
    agriculture = "agriculture"
    logging = "logging"
    settlements = "settlements"
    crop_management = "crop management"


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


@tool("pick_dataset")
async def pick_land_change_dataset(
    state: Annotated[Dict, InjectedState],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
    land_cover: LandUseLandCover = LandUseLandCover.all,
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
        land_cover: The primary land cover or land use type the user is asking about.
            Use `forest` for general forest questions, `primary_forest` for old-growth or intact forest.
            Use `natural_land` for broad natural ecosystem questions. Use `grasslands` for natural/semi-natural
            grassland questions. Use `wetland`, `peatland`, or `mangrove` when the user names those ecosystems.
            Use `built_up` for urban, development, settlements, or infrastructure questions.
            Use `cropland` for agriculture or farming. Use `cultivated_grassland` for cultivated pasture.
        event: The type of change or phenomenon the user is asking about.
            Use `loss` for deforestation or cover loss. Use `gain` for reforestation or cover gain.
            Use `disturbance` for alerts or ecosystem disruptions. Use `change` when the user asks about
            land cover transitions (e.g. "what changed from X to Y"). Use `carbon_emission` or
            `carbon_removal` for carbon flux questions.
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

    result = choose_dataset(land_cover, event, cause, measurement, temporal_resolution)

    if result is None:
        raise ValueError(
            "No dataset is available for the combination of parameters provided. "
            "The requested land cover, event, or measurement may not be supported together."
        )

    dataset_id, context_layer, fallback_note, reason = result

    row = next((ds for ds in DATASETS if ds["dataset_id"] == dataset_id), None)
    if row is None:
        raise ValueError(f"choose_dataset returned unknown dataset_id: {dataset_id}")

    orig_start, orig_end = start_date, end_date
    start_date, end_date, range_clamped = await revise_date_range(start_date, end_date, dataset_id, context_layer)
    if range_clamped:
        reason += f" The requested date range was adjusted to {start_date}–{end_date} to fit the dataset's available data (originally {orig_start}–{orig_end})."

    ns_selection = SimpleNamespace(dataset_id=dataset_id, context_layer=context_layer, parameters=None)
    ns_row = SimpleNamespace(**row)
    tile_url, context_layers_list = get_tile_services_for_dataset(ns_selection, ns_row, start_date, end_date)

    result = DatasetSelectionResult(
        dataset_id=dataset_id,
        dataset_name=row["dataset_name"],
        context_layer=context_layer,
        context_layers=context_layers_list,
        parameters=None,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
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

_FOREST_LAND_COVERS = (LandUseLandCover.forest, LandUseLandCover.primary_forest)
_NATURAL_LAND_COVERS = (LandUseLandCover.natural_land, LandUseLandCover.natural_forest,
                        LandUseLandCover.wetland, LandUseLandCover.peatland, LandUseLandCover.mangrove)
_CARBON_MEASUREMENTS = (Measurement.co2, Measurement.co2e, Measurement.net_flux)

_FOREST_OR_ALL = _FOREST_LAND_COVERS + (LandUseLandCover.all,)
_DATASET_NAMES = {ds["dataset_id"]: ds["dataset_name"] for ds in DATASETS}

def choose_dataset(
    land_cover: LandUseLandCover,
    event,
    cause,
    measurement,
    temporal_resolution,
) -> tuple[int, str | None, str | None, str] | None:
    """Returns (dataset_id, context_layer, note, reason) or None if no dataset matches.

    Decision tree: land_cover → event → cause → measurement → temporal_resolution.
    land_cover always provides a default; each subsequent level refines only when a
    more specific dataset exists for that combination.
    """
    note = None
    lulc = land_cover.value

    # Level 1: land_cover → default dataset
    if land_cover in _FOREST_LAND_COVERS:
        dataset_id = 7  # tree cover (static 2000)
        context_layer = "primary_forest" if land_cover == LandUseLandCover.primary_forest else None
    elif land_cover == LandUseLandCover.grasslands:
        dataset_id = 2  # natural/semi-natural grasslands
        context_layer = None
    elif land_cover in _NATURAL_LAND_COVERS:
        dataset_id = 3  # SBTN natural lands
        context_layer = None
    else:  # all, cropland, built_up, short_vegetation, cultivated_grassland, water, bare_ground
        dataset_id = 1  # global land cover
        context_layer = None

    # Level 2: measurement — carbon always overrides to GHG flux
    if measurement in _CARBON_MEASUREMENTS or event in (Event.carbon_emission, Event.carbon_removal):
        dataset_id = 6
        context_layer = None
        carbon_type = (
            "carbon emissions" if event == Event.carbon_emission
            else "carbon removal" if event == Event.carbon_removal
            else "net carbon flux" if measurement == Measurement.net_flux
            else "carbon measurement"
        )
        if land_cover not in _FOREST_OR_ALL:
            note = f"No carbon data for {lulc}; showing Forest GHG Net Flux"
            reason = f"No carbon data is available for {lulc}, so showing Forest GHG Net Flux as the closest match for your {carbon_type} question."
        else:
            reason = f"Showing Forest GHG Net Flux to answer your {carbon_type} question for {lulc}."

    # Level 2: event → refine if a better dataset exists for this land_cover + event
    elif event == Event.disturbance:
        dataset_id = 0
        if cause is not None:
            cause_label = cause.value
            context_layer = "driver"
            reason = f"Showing DIST-ALERT disturbance alerts filtered by driver because you asked about {lulc} disturbances caused by {cause_label}."
        else:
            context_layer = None
            reason = f"Showing DIST-ALERT disturbance alerts because you asked about {lulc} disturbances."

    elif event == Event.gain:
        if land_cover in _FOREST_OR_ALL:
            dataset_id = 5
            reason = f"Showing Tree Cover Gain because you asked about {lulc} gain."
        else:
            fallback_name = _DATASET_NAMES.get(dataset_id, "the closest dataset")
            note = f"No gain data for {lulc}; showing {fallback_name}"
            reason = f"No gain data is available for {lulc}, so showing {fallback_name} as the closest match."

    elif event in (Event.loss, Event.deforestation):
        if land_cover in _FOREST_OR_ALL:
            # Level 3: cause → refine
            if cause is not None:
                cause_label = cause.value
                dataset_id = 8
                context_layer = "driver"
                reason = f"Showing Tree Cover Loss by Driver because you asked about {lulc} loss caused by {cause_label}."
            else:
                dataset_id = 4
                if event == Event.deforestation or land_cover == LandUseLandCover.primary_forest:
                    context_layer = "primary_forest"
                    reason = f"Showing Tree Cover Loss with a primary forest filter because you asked about {lulc} {event.value}."
                else:
                    context_layer = None
                    reason = f"Showing Tree Cover Loss because you asked about {lulc} loss."
        else:
            fallback_name = _DATASET_NAMES.get(dataset_id, "the closest dataset")
            note = f"No {event.value} data for {lulc}; showing {fallback_name}"
            reason = f"No {event.value} data is available for {lulc}, so showing {fallback_name} as the closest match."

    elif event == Event.change:
        context_layer = None
        if land_cover != LandUseLandCover.grasslands:
            dataset_id = 1  # grasslands already at 2; everything else → land cover change
            reason = f"Showing Global Land Cover because you asked about land cover change involving {lulc}."
        else:
            reason = f"Showing Natural Grasslands because you asked about grassland change."

    else:
        # No event — use land_cover default with a simple explanation
        if land_cover in _FOREST_LAND_COVERS:
            reason = f"Showing Tree Cover extent for your {lulc} question."
        elif land_cover == LandUseLandCover.grasslands:
            reason = f"Showing Natural Grasslands for your grasslands question."
        elif land_cover in _NATURAL_LAND_COVERS:
            reason = f"Showing SBTN Natural Lands for your {lulc} question."
        else:
            reason = f"Showing Global Land Cover for your {lulc} question."

    # Level 4: temporal_resolution — return None so caller raises (no further fallback)
    if temporal_resolution is not None:
        supported = _DATASET_TEMPORAL_RESOLUTIONS.get(dataset_id, set())
        if temporal_resolution not in supported:
            return None

    return dataset_id, context_layer, note, reason