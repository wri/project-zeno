from enum import Enum
from types import SimpleNamespace
from typing import Annotated, Dict, Optional

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


# Q2: Which ecosystem or land type?
class Ecosystem(str, Enum):
    all = "all ecosystems"
    forest = "forest"
    primary_forest = "primary forest"
    grassland = "grassland"
    natural_land = "natural land"
    mangrove = "mangrove"
    wetland = "wetland"
    peatland = "peatland"
    natural_forest = "natural forest"
    short_vegetation = "short vegetation"
    cultivated_grassland = "cultivated grassland"
    cropland = "cropland"
    built_up = "built-up land"
    water = "water"
    bare_ground = "bare ground"


# Q4: What phenomenon or change?
class ChangeType(str, Enum):
    loss = "loss"
    gain = "gain"
    change = "land cover change"
    disturbance = "disturbance"


# Q5: What caused it?
class Cause(str, Enum):
    all = "any cause"
    wildfire = "wildfire"
    agriculture = "agriculture"
    logging = "logging"
    settlements = "settlements"
    crop_management = "crop management"


# Q3: Area/extent or carbon?
class MeasurementType(str, Enum):
    area = "area"
    carbon_emissions = "carbon emissions"
    net_carbon_flux = "net carbon flux"


# Q1 + Q5: Trend, snapshot, or real-time?
class Temporal(str, Enum):
    realtime = "real-time"   # near-real-time alerts → DIST-ALERT
    annual = "annual"        # year-by-year time series
    aggregate = "aggregate"  # totals over the full data period
    snapshot = "snapshot"    # single-year baseline map (e.g. 2020, 2000)


class Definition(BaseModel):
    forest_canopy_cover: Optional[int] = Field(None, description="Canopy cover density percent from 0-100 per 30m pixel", min=0, max=100)


@tool("pick_dataset")
async def pick_land_change_dataset(
    state: Annotated[Dict, InjectedState],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
    ecosystem: Ecosystem = Ecosystem.all,
    change_type: Optional[ChangeType] = None,
    cause: Optional[Cause] = None,
    measurement_type: Optional[MeasurementType] = None,
    definition: Optional[Definition] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    temporal: Optional[Temporal] = None,
) -> Command:
    """
    Picks the appropriate dataset based on five structured questions derived from the user query.
    Set each parameter to the best matching value, or null if not relevant.

    Args:
        ecosystem: Which land or ecosystem type the user is asking about.
            Use `forest` for general forest questions, `primary_forest` for old-growth or intact forest.
            Use `natural_land` for broad natural ecosystem questions. Use `grassland` for natural/semi-natural
            grassland questions. Use `wetland`, `peatland`, or `mangrove` when the user names those ecosystems.
            Use `built_up` for urban, development, settlements, or infrastructure. Use `cropland` for
            agriculture or farming. Default to `all` when no specific ecosystem is mentioned.
        change_type: The phenomenon or change the user is asking about.
            Use `loss` for cover loss or deforestation. Use `gain` for reforestation or cover gain.
            Use `change` when the user asks about transitions between land cover types.
            Use `disturbance` for ecosystem disruption alerts. Leave null for extent/baseline questions.
        cause: Set only when the user specifies what drove the change (e.g. wildfire, agriculture, logging).
            Set to `any cause` if the user asks broadly about causes without naming one.
        measurement_type: What the user wants to quantify.
            Use `area` for extent or hectares — this is the default for loss, gain, and disturbance questions.
            Use `carbon_emissions` when the user asks about CO2 or GHG emitted.
            Use `net_carbon_flux` when the user asks about net carbon balance, sources vs sinks, or net GHG flux.
        definition: Set `forest_canopy_cover` when the user specifies a canopy density threshold
            (e.g. "using 30% canopy cover").
        start_date: Start date in YYYY-MM-DD format, parsed from the user query.
        end_date: End date in YYYY-MM-DD format, parsed from the user query.
        temporal: The temporal structure the user needs.
            Use `realtime` for current or near-real-time alerts. Use `annual` when the user wants a
            year-by-year time series. Use `aggregate` for totals over a multi-year period.
            Use `snapshot` for a fixed single-year baseline (e.g. "as of 2020"). Leave null if not specified.
    """
    logger.info("PICK-DATASET-DECISION-TREE-TOOL")

    result = choose_dataset(ecosystem, change_type, cause, measurement_type, temporal)

    if result is None:
        raise ValueError(
            "No dataset is available for the combination of parameters provided. "
            "The requested ecosystem, change type, or temporal resolution may not be supported together."
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


# Temporal resolutions supported per dataset
_DATASET_TEMPORAL_RESOLUTIONS: dict[int, set[Temporal]] = {
    0: {Temporal.realtime},      # DIST-ALERT
    1: {Temporal.snapshot},      # Global land cover (2015 & 2024 snapshots)
    2: {Temporal.annual},        # Grasslands (annual 2000-2022)
    3: {Temporal.snapshot},      # SBTN Natural Lands (2020 snapshot)
    4: {Temporal.annual},        # Tree cover loss (annual 2001-2025)
    5: {Temporal.aggregate},     # Tree cover gain (cumulative periods)
    6: {Temporal.aggregate},     # Forest GHG net flux (total 2001-2025)
    7: {Temporal.snapshot},      # Tree cover (2000 snapshot)
    8: {Temporal.aggregate},     # TCL by dominant driver (aggregate 2001-2025)
}

_FOREST_ECOSYSTEMS = (Ecosystem.forest, Ecosystem.primary_forest)
_NATURAL_ECOSYSTEMS = (
    Ecosystem.natural_land, Ecosystem.natural_forest,
    Ecosystem.wetland, Ecosystem.peatland, Ecosystem.mangrove,
)
_FOREST_OR_ALL = _FOREST_ECOSYSTEMS + (Ecosystem.all,)
_DATASET_NAMES = {ds["dataset_id"]: ds["dataset_name"] for ds in DATASETS}


def choose_dataset(
    ecosystem: Ecosystem,
    change_type: Optional[ChangeType],
    cause: Optional[Cause],
    measurement_type: Optional[MeasurementType],
    temporal: Optional[Temporal],
) -> tuple[int, str | None, str | None, str] | None:
    """Returns (dataset_id, context_layer, note, reason) or None if no dataset matches.

    Decision order follows the five key questions:
      Q3 carbon → Q1/Q5 realtime/disturbance → Q2 ecosystem default
      → Q4 change type → Q5 cause → temporal validation.
    """
    note = None
    eco = ecosystem.value

    # Q3: Carbon measurement always routes to Forest GHG flux
    if measurement_type in (MeasurementType.carbon_emissions, MeasurementType.net_carbon_flux):
        dataset_id = 6
        context_layer = None
        carbon_type = "net carbon flux" if measurement_type == MeasurementType.net_carbon_flux else "carbon emissions"
        if ecosystem not in _FOREST_OR_ALL:
            note = f"No carbon data for {eco}; showing Forest GHG Net Flux"
            reason = f"No carbon data is available for {eco}; showing Forest GHG Net Flux as the closest match for your {carbon_type} question."
        else:
            reason = f"Showing Forest GHG Net Flux for your {carbon_type} question about {eco}."
        return dataset_id, context_layer, note, reason

    # Q1/Q5: Real-time or disturbance always routes to DIST-ALERT
    if temporal == Temporal.realtime or change_type == ChangeType.disturbance:
        dataset_id = 0
        if cause is not None:
            context_layer = "driver"
            reason = f"Showing DIST-ALERT disturbance alerts filtered by driver because you asked about {eco} disturbances caused by {cause.value}."
        else:
            context_layer = None
            reason = f"Showing DIST-ALERT disturbance alerts for {eco}."
        return dataset_id, context_layer, note, reason

    # Q2: Ecosystem sets the default dataset
    if ecosystem in _FOREST_ECOSYSTEMS:
        dataset_id = 7  # tree cover (2000 baseline)
        context_layer = "primary_forest" if ecosystem == Ecosystem.primary_forest else None
    elif ecosystem == Ecosystem.grassland:
        dataset_id = 2
        context_layer = None
    elif ecosystem in _NATURAL_ECOSYSTEMS:
        dataset_id = 3  # SBTN natural lands
        context_layer = None
    else:  # all, cropland, built_up, short_vegetation, cultivated_grassland, water, bare_ground
        dataset_id = 1  # global land cover
        context_layer = None

    # Q4: Change type refines the dataset
    if change_type == ChangeType.gain:
        if ecosystem in _FOREST_OR_ALL:
            dataset_id = 5
            reason = f"Showing Tree Cover Gain because you asked about {eco} gain."
        else:
            fallback_name = _DATASET_NAMES.get(dataset_id, "the closest dataset")
            note = f"No gain data for {eco}; showing {fallback_name}"
            reason = f"No gain data is available for {eco}; showing {fallback_name} as the closest match."

    elif change_type == ChangeType.loss:
        if ecosystem in _FOREST_OR_ALL:
            # Q5: Cause further refines loss
            if cause is not None:
                dataset_id = 8
                context_layer = "driver"
                reason = f"Showing Tree Cover Loss by Driver because you asked about {eco} loss caused by {cause.value}."
            else:
                dataset_id = 4
                if ecosystem == Ecosystem.primary_forest:
                    context_layer = "primary_forest"
                    reason = f"Showing Tree Cover Loss with a primary forest filter because you asked about {eco} loss."
                else:
                    context_layer = None
                    reason = f"Showing Tree Cover Loss because you asked about {eco} loss."
        else:
            fallback_name = _DATASET_NAMES.get(dataset_id, "the closest dataset")
            note = f"No loss data for {eco}; showing {fallback_name}"
            reason = f"No loss data is available for {eco}; showing {fallback_name} as the closest match."

    elif change_type == ChangeType.change:
        context_layer = None
        if ecosystem != Ecosystem.grassland:
            dataset_id = 1
            reason = f"Showing Global Land Cover because you asked about land cover change involving {eco}."
        else:
            reason = f"Showing Natural Grasslands because you asked about grassland change."

    else:
        # No change type — extent/baseline question, use ecosystem default
        if ecosystem in _FOREST_ECOSYSTEMS:
            reason = f"Showing Tree Cover extent for your {eco} question."
        elif ecosystem == Ecosystem.grassland:
            reason = f"Showing Natural Grasslands for your grasslands question."
        elif ecosystem in _NATURAL_ECOSYSTEMS:
            reason = f"Showing SBTN Natural Lands for your {eco} question."
        else:
            reason = f"Showing Global Land Cover for your {eco} question."

    # Temporal validation: if a temporal was specified that this dataset doesn't support, return None
    if temporal is not None:
        supported = _DATASET_TEMPORAL_RESOLUTIONS.get(dataset_id, set())
        if temporal not in supported:
            return None

    return dataset_id, context_layer, note, reason
