"""Turn one prompt into a plan for the map, with no agent.

Three calls start at the same time:

- Clairic call A (see `extract.py`): the words that name the area, and the
  canopy cover.
- Clairic call B: the time, as a date range. Code makes the range of some
  time words (seasons, quarters, "the last 3 months").
- jev call 1 (see `jev.py`): the dataset and the scope (one area, or
  several). It also asks the `place` and `period` option questions of phase
  1, so that a Clairic failure costs no extra time: when a Clairic call
  fails, the planner uses these jev answers instead.

Then `search_aois` runs on the place, and jev call 2 selects the area from
its results and the context layer of the dataset (and the canopy cover, when
Clairic call A failed). Each decision records the path that gave it
(`ZapDecision.source`).

The planner starts from the current state (`ZapCurrent`) and changes only
what the request names, so a follow-up keeps the forest type, the canopy
cover and the dates. The plan has up to three steps: show the dataset, go to
the area, chart the dataset for the area. The frontend runs them in order.
`ZapPlan.state` is the state after the steps.
"""

import asyncio
from datetime import date
from typing import Optional

import pandas as pd

from src.agent.datasets.config import DATASETS
from src.agent.datasets.dates import revise_date_range
from src.agent.subagents.pick_dataset.schema import (
    DatasetOption,
    DatasetParameter,
    DatasetSelectionResult,
)
from src.agent.subagents.pick_dataset.tool import get_tile_services_for_dataset
from src.api.services.zap import options as o
from src.api.services.zap.extract import (
    PlaceExtraction,
    Range,
    TimeExtraction,
    extract,
    is_map_view,
    place_search_names,
    snap_canopy,
)
from src.api.services.zap.jev import Answer, Question, build_state, decide
from src.api.services.zap.models import (
    ZapAnalysis,
    ZapArea,
    ZapCurrent,
    ZapDecision,
    ZapPlan,
    ZapStep,
)
from src.shared.aoi_search import search_aois
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

CANDIDATES = 8
# A period answer below this probability leaves the dataset's own dates:
# "recent" can split between "last 12 months" and the current year.
PERIOD_THRESHOLD = 0.35

CONTEXT_LABELS = {
    "primary_forest": "Primary forest only: mature humid tropical forest, "
    "for deforestation",
    "intact_forest": "Intact forest landscapes only: large unbroken forest",
}

QUESTION_LABELS = {
    "dataset": "Dataset",
    "place": "Area words",
    "scope": "Scope",
    "period": "Time",
    "area": "Area",
    "context": "Forest type",
    "canopy": "Canopy cover",
}

CATALOG = {ds["dataset_id"]: ds for ds in DATASETS}


def _canopy_values(ds: dict) -> list[int]:
    for param in ds.get("parameters") or []:
        if param["name"] == "canopy_cover":
            return [int(v) for v in param.get("values") or []]
    return []


def _area_option(row: dict) -> str:
    return f"{row['source']}:{row['src_id']}"


def _area_label(row: dict) -> str:
    return f"{row['name']} ({row['subtype']}, {row['source']})"


async def _candidates(words: str, user_id: str) -> list[dict]:
    """The `search_aois` results for the place words. When the words find
    nothing, the cleaned form of the words (see `place_search_names`)."""
    rows: list[dict] = []
    for name in place_search_names(words):
        df = await search_aois(
            name=name, sources=None, user_id=user_id, limit=CANDIDATES
        )
        rows = df.to_dict(orient="records")
        if rows:
            break
    for row in rows:
        bbox = row.get("bbox")
        row["bbox"] = [float(v) for v in bbox] if bbox is not None else None
    return rows


async def _dataset_args(
    dataset_id: int,
    start: Optional[str],
    end: Optional[str],
    context_layer: Optional[str],
    canopy_cover: Optional[int],
) -> DatasetSelectionResult:
    """The `dataset` object that pick_dataset streams, built the same way."""
    ds = CATALOG[dataset_id]
    start, end, _ = await revise_date_range(
        start, end, dataset_id, context_layer
    )
    if start > end:
        # The period is outside the dataset: use all of its dates.
        start, end, _ = await revise_date_range(
            None, None, dataset_id, context_layer
        )
    option = DatasetOption(
        dataset_id=dataset_id,
        context_layer=context_layer,
        selected_layer=None,
        parameters=(
            [
                DatasetParameter(
                    name="canopy_cover", description="", values=[canopy_cover]
                )
            ]
            if canopy_cover is not None
            else None
        ),
        start_date=start,
        end_date=end,
        reason="",
    )
    row = pd.Series(ds)
    tile_url, context_layers, layers = get_tile_services_for_dataset(
        option, row, start, end
    )
    return DatasetSelectionResult(
        **option.model_dump(exclude={"start_date", "end_date"}),
        start_date=start,
        end_date=end,
        tile_url=tile_url or "",
        dataset_name=ds["dataset_name"],
        layers=layers,
        context_layers=context_layers,
        analytics_api_endpoint=ds.get("analytics_api_endpoint") or "",
        description=ds.get("description") or "",
        prompt_instructions=ds.get("prompt_instructions") or "",
        methodology=ds.get("methodology") or "",
        cautions=ds.get("cautions") or "",
        function_usage_notes=ds.get("function_usage_notes") or "",
        citation=ds.get("citation") or "",
        content_date=str(ds.get("content_date") or ""),
    )


def _decision(name: str, question: Question, answer: Answer) -> ZapDecision:
    label = question.options.get(answer.choice, answer.choice)
    if name == "dataset" and answer.choice.isdigit():
        label = CATALOG[int(answer.choice)]["dataset_name"]
    elif len(label) > 80:
        label = label[:77] + "..."
    return ZapDecision(
        question=QUESTION_LABELS[name],
        label=label,
        probability=round(answer.probability, 3),
        source="jev",
    )


def _value_decision(
    name: str, label: str, probability: float, source: str
) -> ZapDecision:
    return ZapDecision(
        question=QUESTION_LABELS[name],
        label=label,
        probability=round(probability, 3),
        source=source,
    )


def _range_label(rng: Range) -> str:
    if rng == (None, None):
        return "The whole record of the dataset"
    return f"{rng[0]} to {rng[1]}"


def _context_label(value: str) -> str:
    return CONTEXT_LABELS.get(value, value).split(":")[0]


def _state_lines(current: ZapCurrent, dataset_name: str) -> dict[str, str]:
    """The current map for the jev state. The time, the forest type and the
    canopy cover are only given when the client sends them."""
    lines = {
        "Dataset": dataset_name,
        "Area": current.area.name if current.area else "not set",
    }
    if current.start_date and current.end_date:
        lines["Time"] = f"{current.start_date} to {current.end_date}"
    if current.context_layer:
        lines["Forest type"] = _context_label(current.context_layer)
    if current.canopy_cover is not None:
        lines["Canopy cover"] = f"at least {current.canopy_cover}%"
    return lines


async def _kept_range(current: ZapCurrent) -> Range:
    """The dates to keep when the request names no time. When the current
    dates are all the dates of the current dataset, the user did not select
    a period: give the whole record of the next dataset."""
    if not (current.start_date and current.end_date):
        return None, None
    if current.dataset_id is not None and current.dataset_id in CATALOG:
        full_start, full_end, _ = await revise_date_range(
            None, None, current.dataset_id, current.context_layer
        )
        if (current.start_date, current.end_date) == (full_start, full_end):
            return None, None
    return current.start_date, current.end_date


async def plan_zap(
    prompt: str,
    current: ZapCurrent,
    user_id: str,
    today: Optional[date] = None,
) -> ZapPlan:
    today = today or date.today()
    current_dataset = (
        CATALOG[current.dataset_id]["dataset_name"]
        if current.dataset_id in CATALOG
        else "not set"
    )
    state = build_state(
        prompt, _state_lines(current, current_dataset), str(today)
    )
    decisions: list[ZapDecision] = []
    notes: list[str] = []

    # Clairic calls A and B and jev call 1, at the same time.
    first = {
        "dataset": Question(
            o.DATASET_INSTRUCTIONS,
            {
                **{str(i): card for i, card in o.DATASET_CARDS.items()},
                o.KEEP: f"Keep the current dataset ({current_dataset})",
            },
        ),
        "place": Question(
            o.PLACE_INSTRUCTIONS,
            {
                **{span: span for span in o.place_spans(prompt)},
                o.KEEP: "The request names no area",
            },
        ),
        "scope": Question(o.SCOPE_INSTRUCTIONS, o.SCOPES),
        "period": Question(
            o.PERIOD_INSTRUCTIONS,
            {
                **o.period_options(today),
                o.KEEP: "The request names no time",
            },
        ),
    }
    (place_x, time_x), answers = await asyncio.gather(
        extract(prompt, today), decide(state, first)
    )
    clairic_place = isinstance(place_x, PlaceExtraction)
    clairic_time = isinstance(time_x, TimeExtraction)
    if not clairic_place:
        logger.warning("zap_clairic_place_failed", error=str(place_x))
    if not clairic_time:
        logger.warning("zap_clairic_time_failed", error=str(time_x))

    for name in ("dataset", "scope"):
        if name in answers:
            decisions.append(_decision(name, first[name], answers[name]))

    dataset_answer = answers.get("dataset")
    new_dataset = (
        int(dataset_answer.choice)
        if dataset_answer and dataset_answer.choice.isdigit()
        else None
    )
    dataset_id = new_dataset or (
        current.dataset_id if current.dataset_id in o.DATASET_CARDS else None
    )

    # The place: Clairic, else the jev span.
    if clairic_place:
        assert isinstance(place_x, PlaceExtraction)
        words = place_x.place or o.KEEP
        decisions.append(
            _value_decision(
                "place",
                place_x.place or "The request names no area",
                place_x.place_probability
                if place_x.place
                else 1 - place_x.place_probability,
                "clairic",
            )
        )
        if words != o.KEEP and is_map_view(words):
            words = o.KEEP
    else:
        words = answers["place"].choice if "place" in answers else o.KEEP
        if "place" in answers:
            decisions.append(
                _decision("place", first["place"], answers["place"])
            )

    scope = answers["scope"].choice if "scope" in answers else "single"
    if scope != "single":
        notes.append(
            "Zap shows one area at a time. Ask the assistant to compare areas "
            "or rank the parts of an area."
        )
        words = o.KEEP

    # The time: Clairic (or a calendar rule), else the jev period.
    requested: Optional[Range] = None
    if clairic_time:
        assert isinstance(time_x, TimeExtraction)
        requested = time_x.range
        decisions.append(
            _value_decision(
                "period",
                _range_label(time_x.range)
                if time_x.range is not None
                else "The request names no time",
                time_x.probability,
                time_x.source,
            )
        )
    else:
        period = answers.get("period")
        if period:
            decisions.append(_decision("period", first["period"], period))
        if (
            period
            and period.choice != o.KEEP
            and period.probability >= PERIOD_THRESHOLD
        ):
            requested = o.period_range(period.choice, today)
    time_named = requested is not None
    start, end = (
        requested if requested is not None else await _kept_range(current)
    )

    # jev call 2: the area, and the options of the dataset.
    second: dict[str, Question] = {}
    candidates: list[dict] = []
    if words != o.KEEP:
        candidates = await _candidates(words, user_id)
        if candidates:
            second["area"] = Question(
                o.AREA_INSTRUCTIONS,
                {
                    **{_area_option(r): _area_label(r) for r in candidates},
                    o.NONE: "None of these areas",
                },
            )
        else:
            notes.append(f"No area found for '{words}'.")
    ds = CATALOG.get(dataset_id) if dataset_id else None
    layers = [
        layer["value"] for layer in (ds or {}).get("context_layers") or []
    ]
    kept_context = (
        current.context_layer if current.context_layer in layers else None
    )
    if layers:
        context_options = {
            value: CONTEXT_LABELS.get(value, value) for value in layers
        }
        if kept_context:
            context_options[o.KEEP] = (
                "The request names no forest type: keep the current one "
                f"({_context_label(kept_context)})"
            )
        context_options[o.NONE] = "All tree cover, no forest type filter"
        second["context"] = Question(
            o.CONTEXT_KEEP_INSTRUCTIONS
            if kept_context
            else o.CONTEXT_INSTRUCTIONS,
            context_options,
        )
    canopy_values = _canopy_values(ds) if ds else []
    kept_canopy = (
        current.canopy_cover
        if canopy_values and current.canopy_cover is not None
        else None
    )
    if kept_canopy is not None and kept_canopy not in canopy_values:
        kept_canopy, _ = snap_canopy(kept_canopy, canopy_values)
    if canopy_values and not clairic_place:
        second["canopy"] = Question(
            o.CANOPY_INSTRUCTIONS,
            {
                **{
                    str(v): f"At least {v}% canopy cover"
                    for v in canopy_values
                },
                o.NONE: "No threshold named (keep the current one)",
            },
        )
    later = await decide(state, second) if second else {}
    later = {k: v for k, v in later.items() if k in second}
    for name, answer in later.items():
        decisions.append(_decision(name, second[name], answer))

    area: Optional[ZapArea] = None
    if "area" in later and later["area"].choice != o.NONE:
        row = next(
            r for r in candidates if _area_option(r) == later["area"].choice
        )
        area = ZapArea(
            name=row["name"],
            source=row["source"],
            src_id=str(row["src_id"]),
            subtype=row.get("subtype"),
            bbox=row.get("bbox"),
        )
    elif "area" in later:
        notes.append(f"None of the areas found for '{words}' fits.")

    context_layer: Optional[str] = None
    if "context" in later:
        choice = later["context"].choice
        if choice == o.KEEP:
            context_layer = kept_context
        elif choice != o.NONE:
            context_layer = choice

    canopy_cover: Optional[int] = kept_canopy
    if clairic_place:
        assert isinstance(place_x, PlaceExtraction)
        if place_x.canopy is not None and canopy_values:
            canopy_cover, note = snap_canopy(place_x.canopy, canopy_values)
            if note:
                notes.append(note)
            decisions.append(
                _value_decision(
                    "canopy",
                    f"At least {canopy_cover}% canopy cover",
                    place_x.canopy_probability,
                    "clairic",
                )
            )
    elif "canopy" in later and later["canopy"].choice.isdigit():
        canopy_cover = int(later["canopy"].choice)

    # The steps.
    steps: list[ZapStep] = []
    current_layers = [
        layer["value"]
        for layer in (CATALOG.get(current.dataset_id) or {}).get(
            "context_layers"
        )
        or []
    ]
    current_context = (
        current.context_layer
        if current.context_layer in current_layers
        else None
    )
    dataset_step = dataset_id is not None and (
        dataset_id != current.dataset_id
        or time_named
        or context_layer != current_context
        or canopy_cover != current.canopy_cover
    )
    result: Optional[DatasetSelectionResult] = None
    dates = ("", "")
    if dataset_id is not None:
        result = await _dataset_args(
            dataset_id, start, end, context_layer, canopy_cover
        )
        # _dataset_args always sets both dates.
        dates = (str(result.start_date), str(result.end_date))
    if dataset_step and result:
        detail = [f"{dates[0][:4]}–{dates[1][:4]}"]
        if context_layer:
            detail.append(context_layer.replace("_", " "))
        if canopy_cover is not None:
            detail.append(f"≥{canopy_cover}% canopy")
        steps.append(
            ZapStep(
                kind="dataset",
                title=f"Show {result.dataset_name}",
                detail=" · ".join(detail),
                args=result.model_dump(),
            )
        )
    if area:
        steps.append(
            ZapStep(
                kind="area",
                title=f"Go to {area.name}",
                detail=f"{area.subtype or ''} · {area.source}".strip(" ·"),
                args=area.model_dump(),
            )
        )
    analysis_area = area or current.area
    if (
        result
        and dataset_id is not None
        and analysis_area
        and (dataset_step or area)
    ):
        analysis = ZapAnalysis(
            dataset_id=dataset_id,
            dataset_name=result.dataset_name,
            area=analysis_area,
            start_date=dates[0],
            end_date=dates[1],
            context_layer=context_layer,
            canopy_cover=canopy_cover,
        )
        steps.append(
            ZapStep(
                kind="analysis",
                title=f"Chart {result.dataset_name}",
                detail=f"for {analysis_area.name}",
                args=analysis.model_dump(),
            )
        )

    # The state after the steps.
    if dataset_step and result:
        after = ZapCurrent(
            dataset_id=dataset_id,
            area=analysis_area,
            start_date=dates[0],
            end_date=dates[1],
            # As the dataset step shows it: tree cover loss by driver always
            # has the "driver" layer (see DatasetOption).
            context_layer=result.context_layer,
            canopy_cover=canopy_cover,
        )
    else:
        after = current.model_copy(update={"area": analysis_area})
        if result and not (current.start_date and current.end_date):
            after.start_date, after.end_date = dates
    return ZapPlan(steps=steps, decisions=decisions, notes=notes, state=after)
