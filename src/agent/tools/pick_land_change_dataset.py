from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Annotated, Dict, Optional

from langchain.tools import InjectedState
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.agent.datasets.config import DATASETS
from src.agent.datasets.dates import revise_date_range
from src.agent.subagents.pick_dataset.schema import DatasetSelectionResult
from src.agent.subagents.pick_dataset.tool import get_tile_services_for_dataset
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
    realtime = "real-time"  # near-real-time alerts → DIST-ALERT
    annual = "annual"  # year-by-year time series
    aggregate = "aggregate"  # totals over the full data period
    snapshot = "snapshot"  # single-year baseline map (e.g. 2020, 2000)


class Definition(BaseModel):
    forest_canopy_cover: Optional[int] = Field(
        None,
        description="Canopy cover density percent from 0-100 per 30m pixel",
        min=0,
        max=100,
    )


# ---------------------------------------------------------------------------
# Scoring system
# ---------------------------------------------------------------------------

SELECTION_THRESHOLD = 3

_FOREST_ECO = frozenset({Ecosystem.forest, Ecosystem.primary_forest})
_NATURAL_ECO = frozenset(
    {
        Ecosystem.natural_land,
        Ecosystem.natural_forest,
        Ecosystem.wetland,
        Ecosystem.peatland,
        Ecosystem.mangrove,
    }
)
_LAND_COVER_ECO = frozenset(
    {
        Ecosystem.built_up,
        Ecosystem.cropland,
        Ecosystem.short_vegetation,
        Ecosystem.cultivated_grassland,
        Ecosystem.water,
        Ecosystem.bare_ground,
    }
)
_GRASSLAND_ECO = frozenset({Ecosystem.grassland})
_FOREST_OR_ALL = _FOREST_ECO | {Ecosystem.all}
_ALL_ECO = frozenset(Ecosystem)

_DATASET_NAMES = {ds["dataset_id"]: ds["dataset_name"] for ds in DATASETS}


@dataclass
class ScoredDataset:
    dataset_id: int
    score: int
    context_layer: Optional[str]
    reason: str


def _score_ecosystem(
    ecosystem: Ecosystem,
    primary: frozenset,
    compatible: frozenset = frozenset(),
) -> int:
    if ecosystem in primary:
        return 3
    if ecosystem in compatible:
        return 1
    if primary:  # dataset has restricted ecosystems; this one doesn't fit
        return -3
    return 0


def _score_change_type(
    change_type: Optional[ChangeType],
    primary: frozenset = frozenset(),
    compatible: frozenset = frozenset(),
    incompatible: frozenset = frozenset(),
) -> int:
    if change_type is None:
        return 0
    if change_type in primary:
        return 3
    if change_type in compatible:
        return 1
    if change_type in incompatible:
        return -2
    return 0


def _score_temporal(temporal: Optional[Temporal], supported: frozenset) -> int:
    if temporal is None:
        return 0
    return 2 if temporal in supported else -3


def _context_layer_for(
    dataset_id: int, ecosystem: Ecosystem, cause: Optional[Cause]
) -> Optional[str]:
    if dataset_id == 0:
        return "driver" if cause is not None else None
    if dataset_id == 4:
        return (
            "primary_forest" if ecosystem == Ecosystem.primary_forest else None
        )
    if dataset_id == 8:
        return "driver"
    return None


def score_datasets(
    ecosystem: Ecosystem,
    change_type: Optional[ChangeType],
    cause: Optional[Cause],
    measurement_type: Optional[MeasurementType],
    temporal: Optional[Temporal],
) -> list[ScoredDataset]:
    """Score all datasets against the input criteria. Returns sorted by score descending."""
    is_carbon = measurement_type in (
        MeasurementType.carbon_emissions,
        MeasurementType.net_carbon_flux,
    )
    is_net_flux = measurement_type == MeasurementType.net_carbon_flux
    has_cause = cause is not None
    cause_is_agri = cause in (Cause.agriculture, Cause.crop_management)

    def _score(ds_id: int) -> tuple[int, str]:
        if ds_id == 0:  # DIST-ALERT
            s = (
                _score_ecosystem(
                    ecosystem, primary=frozenset(), compatible=_ALL_ECO
                )
                + _score_change_type(
                    change_type,
                    primary=frozenset({ChangeType.disturbance}),
                    incompatible=frozenset(
                        {ChangeType.loss, ChangeType.gain, ChangeType.change}
                    ),
                )
                + (2 if has_cause else 0)
                + (-5 if is_carbon else 0)
                + _score_temporal(temporal, frozenset({Temporal.realtime}))
            )
            return (
                s,
                "DIST-ALERT: near-real-time disturbance alerts for any ecosystem.",
            )

        if ds_id == 1:  # Global Land Cover
            s = (
                _score_ecosystem(
                    ecosystem,
                    primary=_LAND_COVER_ECO,
                    compatible=frozenset({Ecosystem.all}) | _NATURAL_ECO,
                )
                + _score_change_type(
                    change_type,
                    primary=frozenset({ChangeType.change}),
                    incompatible=frozenset(
                        {
                            ChangeType.loss,
                            ChangeType.gain,
                            ChangeType.disturbance,
                        }
                    ),
                )
                + (-5 if is_carbon else 0)
                + _score_temporal(temporal, frozenset({Temporal.snapshot}))
            )
            return (
                s,
                "Global Land Cover: land composition snapshot (2024) and transitions (2015→2024).",
            )

        if ds_id == 2:  # Grasslands
            s = (
                _score_ecosystem(ecosystem, primary=_GRASSLAND_ECO)
                + _score_change_type(
                    change_type,
                    primary=frozenset({ChangeType.change}),
                    compatible=frozenset({ChangeType.loss}),
                    incompatible=frozenset(
                        {ChangeType.gain, ChangeType.disturbance}
                    ),
                )
                + (-5 if is_carbon else 0)
                + _score_temporal(temporal, frozenset({Temporal.annual}))
            )
            return (
                s,
                "Natural/semi-natural grasslands: annual extent 2000–2022.",
            )

        if ds_id == 3:  # SBTN Natural Lands
            s = (
                _score_ecosystem(
                    ecosystem,
                    primary=_NATURAL_ECO,
                    compatible=frozenset({Ecosystem.all}),
                )
                + _score_change_type(
                    change_type,
                    incompatible=frozenset(
                        {
                            ChangeType.loss,
                            ChangeType.gain,
                            ChangeType.disturbance,
                            ChangeType.change,
                        }
                    ),
                )
                + (-5 if is_carbon else 0)
                + _score_temporal(temporal, frozenset({Temporal.snapshot}))
            )
            return (
                s,
                "SBTN Natural Lands: natural vs. non-natural land map (2020 snapshot).",
            )

        if ds_id == 4:  # Tree Cover Loss
            s = (
                _score_ecosystem(ecosystem, primary=_FOREST_OR_ALL)
                + _score_change_type(
                    change_type,
                    primary=frozenset({ChangeType.loss}),
                    incompatible=frozenset(
                        {
                            ChangeType.gain,
                            ChangeType.disturbance,
                            ChangeType.change,
                        }
                    ),
                )
                + (
                    -1 if has_cause else 0
                )  # TCL by Driver is better when cause specified
                + (-5 if is_net_flux else 0)
                + _score_temporal(temporal, frozenset({Temporal.annual}))
            )
            return (
                s,
                "Tree Cover Loss: annual loss 2001–2025, with optional GHG emissions.",
            )

        if ds_id == 5:  # Tree Cover Gain
            s = (
                _score_ecosystem(ecosystem, primary=_FOREST_OR_ALL)
                + _score_change_type(
                    change_type,
                    primary=frozenset({ChangeType.gain}),
                    incompatible=frozenset(
                        {
                            ChangeType.loss,
                            ChangeType.disturbance,
                            ChangeType.change,
                        }
                    ),
                )
                + (-5 if is_carbon else 0)
                + _score_temporal(temporal, frozenset({Temporal.aggregate}))
            )
            return (
                s,
                "Tree Cover Gain: cumulative gain 2000–2020 (and sub-periods).",
            )

        if ds_id == 6:  # Forest GHG Net Flux
            s = (
                _score_ecosystem(
                    ecosystem, primary=frozenset(), compatible=_ALL_ECO
                )
                + _score_change_type(
                    change_type,
                    incompatible=frozenset(
                        {ChangeType.disturbance, ChangeType.gain}
                    ),
                )
                + (5 if is_carbon else -2)
                + _score_temporal(temporal, frozenset({Temporal.aggregate}))
            )
            return (
                s,
                "Forest GHG Net Flux: net carbon flux and emissions 2001–2025.",
            )

        if ds_id == 7:  # Tree Cover
            s = (
                _score_ecosystem(
                    ecosystem,
                    primary=_FOREST_ECO,
                    compatible=frozenset({Ecosystem.all}),
                )
                + _score_change_type(
                    change_type,
                    incompatible=frozenset(
                        {
                            ChangeType.loss,
                            ChangeType.gain,
                            ChangeType.disturbance,
                            ChangeType.change,
                        }
                    ),
                )
                + (-5 if is_carbon else 0)
                + _score_temporal(temporal, frozenset({Temporal.snapshot}))
            )
            return s, "Tree Cover: forest extent baseline (2000 snapshot)."

        if ds_id == 8:  # TCL by Dominant Driver
            # Cause is the defining feature: with cause, loss becomes primary
            if has_cause and change_type == ChangeType.loss:
                ct = 3
            elif change_type in (
                ChangeType.gain,
                ChangeType.disturbance,
                ChangeType.change,
            ):
                ct = -2
            elif change_type == ChangeType.loss:
                ct = 1  # compatible but TCL is more specific without a cause
            else:
                ct = 0
            s = (
                _score_ecosystem(ecosystem, primary=_FOREST_OR_ALL)
                + ct
                + (2 if has_cause else 0)
                + (-5 if is_carbon else 0)
                + _score_temporal(temporal, frozenset({Temporal.aggregate}))
            )
            return s, (
                "Tree Cover Loss by Driver: attributes 2001–2025 loss to 7 driver classes "
                "(permanent agriculture, logging, wildfire, etc.) — aggregate only, not annual."
            )

        if ds_id == 9:  # Deforestation sLUC EF
            carbon_score = (3 if cause_is_agri else 1) if is_carbon else 0
            s = (
                _score_ecosystem(
                    ecosystem,
                    primary=frozenset({Ecosystem.forest, Ecosystem.cropland}),
                )
                + _score_change_type(
                    change_type,
                    compatible=frozenset({ChangeType.loss}),
                    incompatible=frozenset(
                        {ChangeType.gain, ChangeType.disturbance}
                    ),
                )
                + carbon_score
                + (2 if cause_is_agri else 0)
                + (-5 if is_net_flux else 0)
                + _score_temporal(temporal, frozenset({Temporal.annual}))
            )
            return s, (
                "Deforestation Emission Factors: crop-specific sLUC emission factors "
                "for 42 agricultural commodities (2020–2024)."
            )

        return 0, ""

    results = []
    for ds_id in range(10):
        score, reason = _score(ds_id)
        results.append(
            ScoredDataset(
                dataset_id=ds_id,
                score=score,
                context_layer=_context_layer_for(ds_id, ecosystem, cause),
                reason=reason,
            )
        )

    return sorted(results, key=lambda x: x.score, reverse=True)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


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

    scored = score_datasets(
        ecosystem, change_type, cause, measurement_type, temporal
    )
    top = scored[0]

    if top.score < SELECTION_THRESHOLD:
        top3 = scored[:3]
        suggestions = "\n".join(
            f"- **{_DATASET_NAMES[d.dataset_id]}**: {d.reason}" for d in top3
        )
        msg = (
            "No single dataset clearly matches your request. "
            "Here are the closest available options:\n\n"
            f"{suggestions}"
        )
        return Command(
            update={"messages": [ToolMessage(msg, tool_call_id=tool_call_id)]}
        )

    dataset_id = top.dataset_id
    context_layer = top.context_layer
    reason = top.reason

    row = next((ds for ds in DATASETS if ds["dataset_id"] == dataset_id), None)
    if row is None:
        raise ValueError(
            f"score_datasets returned unknown dataset_id: {dataset_id}"
        )

    orig_start, orig_end = start_date, end_date
    start_date, end_date, range_clamped = await revise_date_range(
        start_date, end_date, dataset_id, context_layer
    )
    if range_clamped:
        reason += (
            f" The requested date range was adjusted to {start_date}–{end_date} "
            f"to fit the dataset's available data (originally {orig_start}–{orig_end})."
        )

    ns_selection = SimpleNamespace(
        dataset_id=dataset_id, context_layer=context_layer, parameters=None
    )
    ns_row = SimpleNamespace(**row)
    tile_url, context_layers_list = get_tile_services_for_dataset(
        ns_selection, ns_row, start_date, end_date
    )

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
