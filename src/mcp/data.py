"""The data tool: pull statistics for areas from the GNW analytics API.

It runs the agent's checks (`pull_checks`) and the agent's analytics
handler, and stores nothing: the analytics API keeps the result, and the
result id it assigns is the handle. The numbers go back in the tool's text,
because a model given a handle and no numbers invents them.
"""

import csv
import io
from datetime import date
from types import SimpleNamespace
from typing import Annotated, Optional

from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field

from src.agent.datasets.curated_only import (
    CURATED_ONLY_DATA_WITHHELD,
    is_curated_only,
)
from src.agent.datasets.handlers.analytics_handler import (
    LAND_COVER_CHANGE_ID,
    AnalyticsHandler,
)
from src.agent.datasets.pull_checks import (
    PullRefusal,
    plan_pull,
    refuse_dataset,
)
from src.agent.i18n import t
from src.api.services.charts.base import column_to_rows
from src.mcp.areas import format_aoi_id, lookup_areas
from src.mcp.datasets import MCP_EXCLUDED_DATASETS, get_catalog_dataset

MAX_AREAS = 100
# Rows in the structured result.
MAX_ROWS = 1000
# Rows the text renders as CSV; a larger result shows per-column stats.
MAX_TEXT_ROWS = 200

# Tool messages are read by a model, so they are English.
LANGUAGE = "en"


def _parse_date(value: Optional[str], name: str) -> Optional[str]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ToolError(f"{name} must be a date as YYYY-MM-DD.") from exc


def _check_option(ds: dict, context_layer: Optional[str]) -> None:
    layers = [layer["value"] for layer in ds.get("context_layers") or []]
    if context_layer is not None and context_layer not in layers:
        raise ToolError(
            f"{ds['dataset_name']} has no context layer '{context_layer}'. "
            + (
                f"Its context layers: {', '.join(layers)}."
                if layers
                else "It has no context layers."
            )
        )


def _canopy_parameters(ds: dict, canopy_cover: Optional[int]):
    if canopy_cover is None:
        return None
    values = next(
        (
            param.get("values") or []
            for param in ds.get("parameters") or []
            if param["name"] == "canopy_cover"
        ),
        None,
    )
    if values is None:
        raise ToolError(f"{ds['dataset_name']} has no canopy_cover parameter.")
    if canopy_cover not in values:
        raise ToolError(
            f"canopy_cover must be one of {values} for {ds['dataset_name']}."
        )
    return [{"name": "canopy_cover", "values": [canopy_cover]}]


def _sort_key(row: dict, columns: list[str]):
    return tuple(
        (row.get(c) is None, row.get(c) if row.get(c) is not None else 0)
        for c in columns
    )


def _sorted_rows(rows: list[dict]) -> list[dict]:
    """Rows by area, then by any year or date column: the analytics API
    returns them in no particular order."""
    if not rows:
        return rows
    columns = ["name"] + [
        c for c in rows[0] if "year" in c.lower() or "date" in c.lower()
    ]
    columns = [c for c in columns if c in rows[0]]
    try:
        return sorted(rows, key=lambda row: _sort_key(row, columns))
    except TypeError:
        # Mixed types in a column: keep the API's order.
        return rows


async def _rows_text(rows: list[dict], dataset_id: int) -> str:
    """The rows as CSV when there are few enough to read, else per-column
    stats — the view the agent gets of a large series."""
    # Deferred: imported first, inspect_view_context closes an import cycle
    # through src.agent.subagents (the analyst imports it back).
    from src.agent.tools.inspect_view_context import (
        DATA_SKIP_COLUMNS,
        format_chart_data,
    )

    if is_curated_only(dataset_id):
        return CURATED_ONLY_DATA_WITHHELD
    if len(rows) > MAX_TEXT_ROWS or not rows:
        return await format_chart_data(
            SimpleNamespace(chart_data=rows, dataset_id=dataset_id), LANGUAGE
        )
    columns = [c for c in rows[0] if c not in DATA_SKIP_COLUMNS]
    out = io.StringIO()
    writer = csv.DictWriter(
        out, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().rstrip("\n")


async def pull_data(
    aoi_ids: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=MAX_AREAS,
            description=(
                "Area ids from search_areas, e.g. ['gadm:BRA.14_1']. More "
                "than one compares the areas."
            ),
        ),
    ],
    dataset_id: Annotated[
        int, Field(description="The dataset id from list_datasets.")
    ],
    start_date: Annotated[
        Optional[str],
        Field(
            description=(
                "First day, YYYY-MM-DD. Omit for the start of the dataset."
            )
        ),
    ] = None,
    end_date: Annotated[
        Optional[str],
        Field(description="Last day, YYYY-MM-DD. Omit for the latest data."),
    ] = None,
    context_layer: Annotated[
        Optional[str],
        Field(
            description=(
                "Limit the data to a context layer of the dataset, e.g. "
                "'primary_forest'. See get_dataset for the dataset's layers."
            )
        ),
    ] = None,
    canopy_cover: Annotated[
        Optional[int],
        Field(
            description=(
                "Minimum canopy cover in percent, for datasets with a "
                "canopy_cover parameter. Omit for the dataset default."
            )
        ),
    ] = None,
    change_over_time: Annotated[
        bool,
        Field(
            description=(
                "Land cover only: true for the class transitions between "
                "the two years, false for the area of each class."
            )
        ),
    ] = False,
) -> ToolResult:
    """Pull statistics for one or more areas from a dataset.

    Returns the numbers, with the areas, dates and options they are for.
    The date range is fitted to what the dataset covers, and the result says
    so when it was changed. Quote only the numbers this returns, and give
    the dataset's citation.
    """
    ds = get_catalog_dataset(dataset_id)
    _check_option(ds, context_layer)
    parameters = _canopy_parameters(ds, canopy_cover)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")

    # The same dataset fields the agent's pick_dataset sets: the handler
    # reads the forest filter and the canopy cover threshold from them.
    dataset: dict = {
        "dataset_id": ds["dataset_id"],
        "dataset_name": ds["dataset_name"],
    }
    if context_layer:
        dataset["context_layer"] = context_layer
    if parameters:
        dataset["parameters"] = parameters

    refusal = refuse_dataset(dataset, MCP_EXCLUDED_DATASETS)
    if refusal:
        raise ToolError(await t(refusal.key, LANGUAGE, **refusal.kwargs))

    aois = await lookup_areas(aoi_ids)
    plan = await plan_pull(dataset, aois, start, end)
    if isinstance(plan, PullRefusal):
        raise ToolError(await t(plan.key, LANGUAGE, **plan.kwargs))

    areas = [
        {"aoi_id": format_aoi_id(a["source"], a["src_id"]), "name": a["name"]}
        for a in aois
    ]
    result = await AnalyticsHandler().pull_data(
        query="",
        dataset=dataset,
        start_date=plan.start_date,
        end_date=plan.end_date,
        change_over_time_query=(
            change_over_time and ds["dataset_id"] == LAND_COVER_CHANGE_ID
        ),
        # Copies: the handler strips the GADM version suffix in place.
        aois=[dict(aoi) for aoi in aois],
    )
    if not result.success:
        # The handler's reason can hold a full API response, so it is cut.
        raise ToolError(
            await t(
                "pull_data.no_data", LANGUAGE, dataset_name=ds["dataset_name"]
            )
            + f" {(result.message or '')[:500]}"
        )

    rows = _sorted_rows(
        column_to_rows(result.data) if isinstance(result.data, dict) else []
    )
    curated_only = is_curated_only(ds["dataset_id"])
    source_url = result.analytics_api_url
    options = []
    if context_layer:
        options.append(f"context layer {context_layer}")
    if canopy_cover is not None:
        options.append(f"canopy cover >= {canopy_cover}%")

    lines = [
        f"{ds['dataset_name']} for {'; '.join(a['name'] for a in areas)}, "
        f"{plan.start_date} to {plan.end_date}"
        + (f" ({', '.join(options)})" if options else "")
        + f": {len(rows)} rows.",
    ]
    if plan.clamped:
        lines.append(
            "The date range was fitted to the dataset's coverage (requested "
            f"{start_date or 'start'} to {end_date or 'end'}). Tell the user."
        )
    lines.append(await _rows_text(rows, ds["dataset_id"]))
    lines.append(f"Citation: {' '.join(str(ds.get('citation', '')).split())}")
    lines.append(
        "Quote only numbers shown here. Read the cautions with get_dataset "
        "before interpreting them."
    )

    return ToolResult(
        content="\n".join(lines),
        structured_content={
            "result_id": source_url.rsplit("/", 1)[-1] if source_url else None,
            "source_url": source_url,
            "dataset_id": ds["dataset_id"],
            "dataset_name": ds["dataset_name"],
            "areas": areas,
            "start_date": plan.start_date,
            "end_date": plan.end_date,
            "date_range_clamped": plan.clamped,
            "context_layer": context_layer,
            "canopy_cover": canopy_cover,
            "row_count": len(rows),
            # A curated-only dataset's rows are never handed to a model.
            "rows": [] if curated_only else rows[:MAX_ROWS],
            "rows_truncated": len(rows) > MAX_ROWS,
        },
    )
