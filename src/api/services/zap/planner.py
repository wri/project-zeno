"""Turn one prompt into a plan for the map, with no agent.

Two jev calls (see `jev.py`):

1. The dataset, the words of the prompt that name the area, the scope (one
   area, or several) and the time period.
2. The area, from the `search_aois` results for those words, and the context
   layer and canopy cover of the dataset. Only asked when there is something
   to ask.

The plan has up to three steps: show the dataset, go to the area, chart the
dataset for the area. The frontend runs them in order. Each question has a
"keep" or "none" option, so a prompt can change nothing.
"""

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
    df = await search_aois(
        name=words, sources=None, user_id=user_id, limit=CANDIDATES
    )
    rows = df.to_dict(orient="records")
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
    )


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
        prompt,
        {
            "Dataset": current_dataset,
            "Area": current.area.name if current.area else "not set",
        },
        str(today),
    )
    decisions: list[ZapDecision] = []
    notes: list[str] = []

    # Call 1: dataset, area words, scope, period.
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
    answers = await decide(state, first)
    for name, answer in answers.items():
        decisions.append(_decision(name, first[name], answer))

    dataset_answer = answers.get("dataset")
    new_dataset = (
        int(dataset_answer.choice)
        if dataset_answer and dataset_answer.choice.isdigit()
        else None
    )
    dataset_id = new_dataset or (
        current.dataset_id if current.dataset_id in o.DATASET_CARDS else None
    )

    scope = answers["scope"].choice if "scope" in answers else "single"
    words = answers["place"].choice if "place" in answers else o.KEEP
    if scope != "single":
        notes.append(
            "Zap shows one area at a time. Ask the assistant to compare areas "
            "or rank the parts of an area."
        )
        words = o.KEEP

    start: Optional[str] = None
    end: Optional[str] = None
    period = answers.get("period")
    period_changed = bool(
        period
        and period.choice != o.KEEP
        and period.probability >= PERIOD_THRESHOLD
    )
    if period and period_changed:
        start, end = o.period_range(period.choice, today)

    # Call 2: the area, and the options of the dataset.
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
    if ds and ds.get("context_layers"):
        second["context"] = Question(
            o.CONTEXT_INSTRUCTIONS,
            {
                **{
                    layer["value"]: CONTEXT_LABELS.get(
                        layer["value"], layer["value"]
                    )
                    for layer in ds["context_layers"]
                },
                o.NONE: "All tree cover, no forest type filter",
            },
        )
    if ds and _canopy_values(ds):
        second["canopy"] = Question(
            o.CANOPY_INSTRUCTIONS,
            {
                **{
                    str(v): f"At least {v}% canopy cover"
                    for v in _canopy_values(ds)
                },
                o.NONE: "No threshold named (the default, 30%)",
            },
        )
    later = await decide(state, second) if second else {}
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

    context_layer = (
        later["context"].choice
        if "context" in later and later["context"].choice != o.NONE
        else None
    )
    canopy_cover = (
        int(later["canopy"].choice)
        if "canopy" in later and later["canopy"].choice.isdigit()
        else None
    )

    # The steps.
    steps: list[ZapStep] = []
    dataset_step = dataset_id is not None and (
        new_dataset not in (None, current.dataset_id)
        or period_changed
        or context_layer is not None
        or canopy_cover is not None
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
    return ZapPlan(steps=steps, decisions=decisions, notes=notes)
