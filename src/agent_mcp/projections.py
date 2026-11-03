"""MCP tool results projected into the state keys the frontend reads.

The frontend (project-zeno-next, ``processStreamMessage``) dispatches on the
tool name and reads the state keys of the same stream update: ``pick_aoi``
needs ``aoi_selection``, ``pick_dataset`` needs a ``dataset`` with its map
layers, ``generate_insights`` needs ``charts_data``. Each projection takes
the call's arguments and the tool's structured result and returns that
update. Tools write state through these; no tool reads it.
"""

import uuid
from typing import Awaitable, Callable, Optional

import pandas as pd

from src.agent.datasets.config import DATASETS, resolve_selected_layer
from src.agent.datasets.dates import revise_date_range
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.pick_dataset.schema import (
    DatasetOption,
    DatasetParameter,
)
from src.agent.subagents.pick_dataset.tool import (
    get_tile_services_for_dataset,
)

# The empty nudge pick_aoi and pick_dataset write on a selection, so a
# choice offered earlier stops showing.
NO_NUDGE = {"type": "", "options": []}

# Catalog fields the dataset card and the analyst read, as pick_dataset
# writes them.
_CATALOG_FIELDS = (
    "analytics_api_endpoint",
    "description",
    "prompt_instructions",
    "methodology",
    "cautions",
    "function_usage_notes",
    "citation",
    "content_date",
    "selection_hints",
    "code_instructions",
    "presentation_instructions",
)

Projection = Callable[[dict, dict], Awaitable[dict]]


def state_aoi(area: dict) -> dict:
    """An MCP area as an ``aoi_selection`` entry (``AOI`` in the frontend)."""
    source, _, src_id = area["aoi_id"].partition(":")
    return {
        "name": area["name"],
        "source": source,
        "src_id": src_id,
        "subtype": area["subtype"],
        "bbox": area.get("bbox"),
    }


def aoi_id(aoi: dict) -> str:
    """The MCP area id of an ``aoi_selection`` entry."""
    return f"{aoi['source']}:{aoi['src_id']}"


async def project_areas(args: dict, result: dict) -> dict:
    if result.get("areas"):
        return {
            "aoi_selection": {
                "name": result.get("selection_name")
                or result["areas"][0]["name"],
                "aois": [state_aoi(area) for area in result["areas"]],
            },
            "nudge": NO_NUDGE,
        }
    candidates = result.get("candidates") or []
    if candidates:
        # Clicking an option sends its text as the next message, which the
        # model passes back to pick_aoi.
        return {
            "nudge": {
                "type": "aoi_choice",
                "options": [
                    f"{area['name']} ({area['subtype']})"
                    for area in candidates
                ],
                "data": [state_aoi(area) for area in candidates],
            }
        }
    return {}


def _catalog_row(dataset_id: int) -> pd.Series:
    ds = next(ds for ds in DATASETS if ds["dataset_id"] == dataset_id)
    return pd.Series(
        {"tile_url": None, "context_layers": None, "parameters": [], **ds}
    )


def _canopy_parameters(
    canopy_cover: Optional[int],
) -> Optional[list[DatasetParameter]]:
    if canopy_cover is None:
        return None
    return [
        DatasetParameter(
            name="canopy_cover",
            description="Canopy cover threshold (%).",
            values=[canopy_cover],
        )
    ]


async def project_dataset(args: dict, result: dict) -> dict:
    dataset_id = result["dataset_id"]
    row = _catalog_row(dataset_id)
    start_date, end_date, _ = await revise_date_range(
        args.get("start_date"),
        args.get("end_date"),
        dataset_id,
        args.get("context_layer"),
    )
    option = DatasetOption(
        dataset_id=dataset_id,
        context_layer=args.get("context_layer"),
        selected_layer=resolve_selected_layer(dataset_id, None),
        parameters=_canopy_parameters(args.get("canopy_cover")),
        start_date=start_date,
        end_date=end_date,
        reason=args.get("reason") or "",
    )
    tile_url, context_layers, layers = get_tile_services_for_dataset(
        option, row, start_date, end_date
    )
    dataset = {
        **option.model_dump(),
        "dataset_name": result["dataset_name"],
        "tile_url": tile_url,
        "layers": [layer.model_dump() for layer in layers],
        "context_layers": [layer.model_dump() for layer in context_layers],
        **{key: row.get(key) or "" for key in _CATALOG_FIELDS},
    }
    return {"dataset": dataset, "nudge": NO_NUDGE}


def _statistics(result: dict) -> dict:
    areas = [state_aoi(area) for area in result.get("areas") or []]
    return {
        "id": result.get("result_id"),
        "dataset_name": result["dataset_name"],
        "dataset_id": result["dataset_id"],
        "start_date": result["start_date"],
        "end_date": result["end_date"],
        "source_url": result.get("source_url"),
        "data": {},
        "aoi_names": [aoi["name"] for aoi in areas],
        "aoi_ids": [aoi["src_id"] for aoi in areas],
        "aoi_sources": [aoi["source"] for aoi in areas],
        "parameters": (
            [{"name": "canopy_cover", "values": [result["canopy_cover"]]}]
            if result.get("canopy_cover") is not None
            else None
        ),
        "context_layer": result.get("context_layer"),
    }


async def project_pull(args: dict, result: dict) -> dict:
    return {
        "start_date": result["start_date"],
        "end_date": result["end_date"],
        "statistics": [_statistics(result)],
    }


async def project_charts(args: dict, result: dict) -> dict:
    # Nothing is saved, so there is no insight id. A fresh prefix still
    # keeps the chart ids of two analyses apart (the frontend groups the
    # charts of one analysis by it).
    batch = str(uuid.uuid4())
    charts = [InsightChart(**spec) for spec in result.get("charts") or []]
    return {
        "start_date": result["start_date"],
        "end_date": result["end_date"],
        # Empty parts mark the charts as curated.
        "codeact_parts": [],
        "charts_data": [chart.to_frontend_dict(batch) for chart in charts],
    }


PROJECTIONS: dict[str, Projection] = {
    "pick_aoi": project_areas,
    "pick_dataset": project_dataset,
    "pull_data": project_pull,
    "generate_insights": project_charts,
}
