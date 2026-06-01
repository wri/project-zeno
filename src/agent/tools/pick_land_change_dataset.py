from dataclasses import dataclass
from datetime import date
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
# Scoring — one class per dataset
#
# Each dataset subclasses DatasetScorer and implements score() to return
# 0 / 1 / 2 per criterion:
#   2 = exact / primary match
#   1 = close match (the dataset covers it but isn't specialised for it)
#   0 = not supported
#
# Criteria are only added to the total when the caller supplied them.
# eco_score() is also called separately to filter ecosystem-irrelevant
# datasets out of the suggestions list.
# ---------------------------------------------------------------------------

DATASET_NAMES = {ds["dataset_id"]: ds["dataset_name"] for ds in DATASETS}


@dataclass
class ScoredDataset:
    dataset_id: int
    score: int
    context_layer: Optional[str]
    reason: str


class DatasetScorer:
    dataset_id: int
    reason: str

    def eco_score(self, ecosystem: Ecosystem) -> int:
        return 0

    def score(
        self,
        ecosystem: Ecosystem,
        change_type: Optional[ChangeType],
        cause: Optional[Cause],
        measurement_type: Optional[MeasurementType],
        temporal: Optional[Temporal],
    ) -> int:
        raise NotImplementedError

    def context_layer(
        self, ecosystem: Ecosystem, cause: Optional[Cause]
    ) -> Optional[str]:
        return None


class DistAlert(DatasetScorer):
    dataset_id = 0
    reason = "near-real-time disturbance alerts across all ecosystems (from Dec 2023)"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        return (
            2 if ecosystem == Ecosystem.all else 1
        )  # monitors every ecosystem equally

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        if change_type is not None:
            total += 2 if change_type == ChangeType.disturbance else 0
        if cause is not None:
            total += 2  # has driver / cause attribution for all alerts
        if measurement_type is not None:
            total += 2 if measurement_type == MeasurementType.area else 0
        if temporal is not None:
            total += 2 if temporal == Temporal.realtime else 0
        return total

    def context_layer(self, ecosystem, cause):
        return "driver" if cause is not None else None


class GlobalLandCover(DatasetScorer):
    dataset_id = 1
    reason = "land cover classes and transitions 2015–2024"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        if ecosystem in (
            Ecosystem.built_up,
            Ecosystem.cropland,
            Ecosystem.short_vegetation,
            Ecosystem.cultivated_grassland,
            Ecosystem.water,
            Ecosystem.bare_ground,
        ):
            return 2  # these are primary land-cover classes tracked by this dataset
        if ecosystem in (
            Ecosystem.forest,
            Ecosystem.grassland,
            Ecosystem.natural_land,
            Ecosystem.wetland,
            Ecosystem.peatland,
            Ecosystem.mangrove,
            Ecosystem.natural_forest,
            Ecosystem.all,
        ):
            return (
                1  # present as a class but dataset isn't specialised for these
            )
        return 0  # primary_forest not tracked as a distinct class

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        if change_type is not None:
            total += {
                ChangeType.change: 2,
                ChangeType.loss: 1,  # can show class disappearance but not the primary use
                ChangeType.gain: 1,
            }.get(change_type, 0)
        if measurement_type is not None:
            total += 2 if measurement_type == MeasurementType.area else 0
        if temporal is not None:
            total += 2 if temporal == Temporal.snapshot else 0
        return total


class Grasslands(DatasetScorer):
    dataset_id = 2
    reason = "natural/semi-natural grassland extent 2000–2022, annual"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        return 2 if ecosystem == Ecosystem.grassland else 0

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        if change_type is not None:
            total += {ChangeType.change: 2, ChangeType.loss: 1}.get(
                change_type, 0
            )
        if measurement_type is not None:
            total += 2 if measurement_type == MeasurementType.area else 0
        if temporal is not None:
            total += 2 if temporal == Temporal.annual else 0
        return total


class SBTNNaturalLands(DatasetScorer):
    dataset_id = 3
    reason = "natural vs. non-natural land baseline (2020 snapshot)"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        if ecosystem in (
            Ecosystem.natural_land,
            Ecosystem.natural_forest,
            Ecosystem.wetland,
            Ecosystem.peatland,
            Ecosystem.mangrove,
        ):
            return 2
        if ecosystem == Ecosystem.all:
            return 1
        return 0

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        # snapshot only — no change_type or cause attribution
        if measurement_type is not None:
            total += 2 if measurement_type == MeasurementType.area else 0
        if temporal is not None:
            total += 2 if temporal == Temporal.snapshot else 0
        return total


class TreeCoverLoss(DatasetScorer):
    dataset_id = 4
    reason = "annual tree cover loss 2001–2025"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        if ecosystem in (Ecosystem.forest, Ecosystem.primary_forest):
            return 2
        if ecosystem == Ecosystem.all:
            return 1
        return 0

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        if change_type is not None:
            total += 2 if change_type == ChangeType.loss else 0
        if measurement_type is not None:
            total += {
                MeasurementType.area: 2,
                MeasurementType.carbon_emissions: 1,  # optional GHG layer available
            }.get(measurement_type, 0)
        if temporal is not None:
            total += 2 if temporal == Temporal.annual else 0
        return total

    def context_layer(self, ecosystem, cause):
        return (
            "primary_forest" if ecosystem == Ecosystem.primary_forest else None
        )


class TreeCoverGain(DatasetScorer):
    dataset_id = 5
    reason = "cumulative tree cover gain 2000–2020"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        if ecosystem in (Ecosystem.forest, Ecosystem.primary_forest):
            return 2
        if ecosystem == Ecosystem.all:
            return 1
        return 0

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        if change_type is not None:
            total += 2 if change_type == ChangeType.gain else 0
        if measurement_type is not None:
            total += 2 if measurement_type == MeasurementType.area else 0
        if temporal is not None:
            total += 2 if temporal == Temporal.aggregate else 0
        return total


class ForestGHGNetFlux(DatasetScorer):
    dataset_id = 6
    reason = "forest carbon emissions and net flux 2001–2025, aggregate"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        if ecosystem == Ecosystem.forest:
            return 2
        if ecosystem in (
            Ecosystem.primary_forest,
            Ecosystem.natural_land,
            Ecosystem.wetland,
            Ecosystem.peatland,
            Ecosystem.all,
        ):
            return (
                1  # covers adjacent natural ecosystems but forest is primary
            )
        return 0

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        if change_type is not None:
            total += {ChangeType.loss: 1, ChangeType.change: 1}.get(
                change_type, 0
            )
        if measurement_type is not None:
            total += {
                MeasurementType.carbon_emissions: 2,
                MeasurementType.net_carbon_flux: 2,
            }.get(measurement_type, 0)
        if temporal is not None:
            total += 2 if temporal == Temporal.aggregate else 0
        return total


class TreeCover(DatasetScorer):
    dataset_id = 7
    reason = "forest extent baseline (2000 snapshot)"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        if ecosystem in (Ecosystem.forest, Ecosystem.primary_forest):
            return 2
        if ecosystem == Ecosystem.all:
            return 1
        return 0

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        # extent baseline only — no change_type or cause attribution
        if measurement_type is not None:
            total += 2 if measurement_type == MeasurementType.area else 0
        if temporal is not None:
            total += 2 if temporal == Temporal.snapshot else 0
        return total


class TreeCoverLossByDriver(DatasetScorer):
    dataset_id = 8
    reason = "2001–2025 tree cover loss attributed to 7 driver classes, aggregate only"

    def eco_score(self, ecosystem: Ecosystem) -> int:
        if ecosystem in (Ecosystem.forest, Ecosystem.primary_forest):
            return 2
        if ecosystem in (Ecosystem.all, Ecosystem.built_up):
            return 1  # built_up: tracks forest lost to settlements / urban expansion
        return 0

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        if change_type is not None:
            if change_type == ChangeType.loss:
                # exact only when cause is also specified — without a cause, annual TCL is better
                total += 2 if cause is not None else 1
        if cause is not None:
            total += (
                2
                if cause
                in (
                    Cause.wildfire,
                    Cause.agriculture,
                    Cause.logging,
                    Cause.settlements,
                )
                else 1
            )  # crop_management / all → close match
        if measurement_type is not None:
            total += {
                MeasurementType.area: 2,
                MeasurementType.carbon_emissions: 1,
            }.get(measurement_type, 0)
        if temporal is not None:
            total += 2 if temporal == Temporal.aggregate else 0
        return total

    def context_layer(self, ecosystem, cause):
        return "driver"


class DeforestationSLUCEF(DatasetScorer):
    dataset_id = 9
    reason = (
        "emission factors for 42 agricultural commodities 2020–2024, annual"
    )

    def eco_score(self, ecosystem: Ecosystem) -> int:
        if ecosystem == Ecosystem.forest:
            return 2  # tracks forest cleared for agriculture
        if ecosystem in (Ecosystem.primary_forest, Ecosystem.cropland):
            return 1
        return 0

    def score(
        self, ecosystem, change_type, cause, measurement_type, temporal
    ) -> int:
        total = self.eco_score(ecosystem)
        if change_type is not None:
            total += 1 if change_type == ChangeType.loss else 0
        if cause is not None:
            total += (
                2 if cause in (Cause.agriculture, Cause.crop_management) else 0
            )
        if measurement_type is not None:
            total += (
                2
                if measurement_type == MeasurementType.carbon_emissions
                else 0
            )
        if temporal is not None:
            total += 2 if temporal == Temporal.annual else 0
        return total


SCORERS: list[DatasetScorer] = [
    DistAlert(),
    GlobalLandCover(),
    Grasslands(),
    SBTNNaturalLands(),
    TreeCoverLoss(),
    TreeCoverGain(),
    ForestGHGNetFlux(),
    TreeCover(),
    TreeCoverLossByDriver(),
    DeforestationSLUCEF(),
]

SCORER_BY_ID = {scorer.dataset_id: scorer for scorer in SCORERS}


def date_score(
    dataset_id: int, start_date: Optional[str], end_date: Optional[str]
) -> int:
    """0/1/2 based on how well the user's date range overlaps the dataset's coverage."""
    row = next(ds for ds in DATASETS if ds["dataset_id"] == dataset_id)
    dataset_start = row.get("start_date") or "1900-01-01"
    dataset_end = row.get("end_date") or date.today().isoformat()

    if start_date and end_date:
        if start_date >= dataset_start and end_date <= dataset_end:
            return 2
        if start_date <= dataset_end and end_date >= dataset_start:
            return 1
        return 0
    elif start_date:
        if dataset_start <= start_date <= dataset_end:
            return 2
        if start_date < dataset_start:
            return 1  # dataset starts later but still covers part of the requested range
        return 0
    else:  # only end_date
        if dataset_start <= end_date <= dataset_end:
            return 2
        if end_date > dataset_end:
            return 1  # dataset ends before user's end date but still overlaps
        return 0


def score_datasets(
    ecosystem: Ecosystem,
    change_type: Optional[ChangeType],
    cause: Optional[Cause],
    measurement_type: Optional[MeasurementType],
    temporal: Optional[Temporal],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[ScoredDataset]:
    """Score all 10 datasets 0–2 per provided criterion. Returns sorted by score descending.

    A dataset is selected only when it scores 2 on every criterion the caller supplied
    (score == max_score). Anything less goes to suggestions.
    """
    has_dates = bool(start_date or end_date)
    results = []
    for scorer in SCORERS:
        total = scorer.score(
            ecosystem, change_type, cause, measurement_type, temporal
        )
        if has_dates:
            total += date_score(scorer.dataset_id, start_date, end_date)
        results.append(
            ScoredDataset(
                dataset_id=scorer.dataset_id,
                score=total,
                context_layer=scorer.context_layer(ecosystem, cause),
                reason=scorer.reason,
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

    max_score = 2 * sum(
        [
            1,  # ecosystem always provided
            change_type is not None,
            cause is not None,
            measurement_type is not None,
            temporal is not None,
            bool(start_date or end_date),
        ]
    )

    scored = score_datasets(
        ecosystem,
        change_type,
        cause,
        measurement_type,
        temporal,
        start_date,
        end_date,
    )
    top = scored[0]

    if top.score < max_score:
        # Only suggest datasets that at least cover the queried ecosystem (eco_score > 0)
        relevant = [
            d
            for d in scored
            if SCORER_BY_ID[d.dataset_id].eco_score(ecosystem) > 0
        ]
        top3 = relevant[:3] if relevant else scored[:3]
        suggestions = "\n".join(
            f"- **{DATASET_NAMES[d.dataset_id]}**: {d.reason}" for d in top3
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

    start_date = start_date or row.get("start_date")
    end_date = end_date or row.get("end_date") or date.today().isoformat()

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
