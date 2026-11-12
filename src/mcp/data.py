"""The data tool: pull statistics for areas from the GNW analytics API.

It runs the agent's checks (`pull_checks`) and the agent's analytics
handler, and stores nothing: the analytics API keeps the result, and the
result id it assigns is the handle. The numbers go back in the tool's text,
because a model given a handle and no numbers invents them.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
)
from src.agent.i18n import t
from src.api.services.charts.base import column_to_rows
from src.mcp.areas import MAX_AREAS, format_aoi_id, lookup_areas
from src.mcp.datasets import get_catalog_dataset
from src.mcp.script import pull_script, rows_digest
from src.shared.version import get_commit, get_version

# Rows in the structured result.
MAX_ROWS = 1000
# The text shows the rows as CSV when there are at most MAX_TEXT_ROWS of them
# and the CSV fits in TEXT_CHAR_BUDGET characters (about 2,000 tokens; one
# budget for all the charts of curated_charts). Otherwise it shows
# per-column stats. Characters, not tokens: the client's model, and so its
# tokenizer, is not known. The structured rows and pull.py have every row.
MAX_TEXT_ROWS = 200
TEXT_CHAR_BUDGET = 7000
# Area names in the text's first line. A subregion expansion has hundreds,
# and naming them all would outgrow the budget the rows keep to.
MAX_HEADING_AREAS = 10

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


def text_number(value):
    """A number as the text shows it: two decimals, or four significant
    digits below 1. The rows the API returned carry up to 17 digits, which
    cost tokens and say nothing more."""
    if isinstance(value, float) and value == value:
        return (
            float(f"{value:.2f}") if abs(value) >= 1 else float(f"{value:.4g}")
        )
    return value


def text_csv(rows: list[dict]) -> str:
    """Rows as the text shows them: CSV without the id columns, rounded."""
    # Deferred: imported first, inspect_view_context closes an import cycle
    # through src.agent.subagents (the analyst imports it back).
    from src.agent.tools.inspect_view_context import DATA_SKIP_COLUMNS

    return rows_csv(
        [
            {key: text_number(value) for key, value in row.items()}
            for row in rows
        ],
        skip=DATA_SKIP_COLUMNS,
    )


async def rows_text(
    rows: list[dict],
    dataset_id: int,
    budget: int = TEXT_CHAR_BUDGET,
    where: Optional[str] = None,
) -> str:
    """The rows as rounded CSV when there are at most MAX_TEXT_ROWS and the
    CSV fits in `budget` characters; else per-column stats, the view the
    agent gets of a large series, and `where` the rows are (by default,
    where a pull's rows are)."""
    from src.agent.tools.inspect_view_context import format_chart_data

    if is_curated_only(dataset_id):
        return CURATED_ONLY_DATA_WITHHELD
    if rows and len(rows) <= MAX_TEXT_ROWS:
        text = text_csv(rows)
        if len(text) <= budget:
            return text
    stats = await format_chart_data(
        SimpleNamespace(chart_data=rows, dataset_id=dataset_id), LANGUAGE
    )
    if not rows:
        return stats
    if where is None:
        where = (
            "The structured result and pull.py hold all of them."
            if len(rows) <= MAX_ROWS
            else f"The structured result holds the first {MAX_ROWS}; "
            "pull.py writes all of them."
        )
    return (
        f"{stats}\nThese {len(rows)} rows are too large to show here. "
        f"{where} Do not estimate a value this summary does not give."
    )


def rows_csv(rows: list[dict], skip=()) -> str:
    """Rows as CSV: every column any row has, less `skip`."""
    columns: dict = {}
    for row in rows:
        columns.update(dict.fromkeys(c for c in row if c not in skip))
    out = io.StringIO()
    writer = csv.DictWriter(
        out,
        fieldnames=list(columns),
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().rstrip("\n")


# The arguments of a pull, shared by pull_data and curated_charts.
AoiIds = Annotated[
    list[str],
    Field(
        min_length=1,
        max_length=MAX_AREAS,
        description=(
            "Area ids from resolve_areas or search_areas, e.g. "
            "['gadm:BRA.14_1']. More than one compares the areas."
        ),
    ),
]
DatasetId = Annotated[
    int, Field(description="The dataset id from list_datasets.")
]
StartDate = Annotated[
    Optional[str],
    Field(
        description="First day, YYYY-MM-DD. Omit for the start of the dataset."
    ),
]
EndDate = Annotated[
    Optional[str],
    Field(description="Last day, YYYY-MM-DD. Omit for the latest data."),
]
ContextLayer = Annotated[
    Optional[str],
    Field(
        description=(
            "Limit the data to a context layer of the dataset, e.g. "
            "'primary_forest'. See get_dataset for the dataset's layers."
        )
    ),
]
CanopyCover = Annotated[
    Optional[int],
    Field(
        description=(
            "Minimum canopy cover in percent, for datasets with a "
            "canopy_cover parameter. Omit for the dataset default."
        )
    ),
]
ChangeOverTime = Annotated[
    bool,
    Field(
        description=(
            "Land cover only: true for the class transitions between "
            "the two years, false for the area of each class."
        )
    ),
]


@dataclass
class Pull:
    """One pull's rows and what they are for."""

    ds: dict
    areas: list[dict]
    start_date: str
    end_date: str
    clamped: bool
    context_layer: Optional[str]
    canopy_cover: Optional[int]
    rows: list[dict]
    source_url: Optional[str]
    # The request sent to the analytics API, as AnalyticsHandler recorded it,
    # and the metadata the API answered with.
    request: Optional[dict]
    metadata: Optional[dict]
    retrieved_at: str
    rows_sha256: str

    def heading(self) -> str:
        options = []
        if self.context_layer:
            options.append(f"context layer {self.context_layer}")
        if self.canopy_cover is not None:
            options.append(f"canopy cover >= {self.canopy_cover}%")
        names = "; ".join(a["name"] for a in self.areas[:MAX_HEADING_AREAS])
        if len(self.areas) > MAX_HEADING_AREAS:
            names += f" and {len(self.areas) - MAX_HEADING_AREAS} more"
        return (
            f"{self.ds['dataset_name']} for {names}, "
            f"{self.start_date} to {self.end_date}"
            + (f" ({', '.join(options)})" if options else "")
        )

    def provenance(self) -> dict:
        """The keys a saved insight names its source by. A public contract:
        do not rename them."""
        return {
            "result_id": (
                self.source_url.rsplit("/", 1)[-1] if self.source_url else None
            ),
            "source_url": self.source_url,
            "dataset_id": self.ds["dataset_id"],
            "dataset_name": self.ds["dataset_name"],
            "areas": self.areas,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "date_range_clamped": self.clamped,
            "context_layer": self.context_layer,
            "canopy_cover": self.canopy_cover,
            "request": self.request,
            "analytics_metadata": self.metadata,
            "retrieved_at": self.retrieved_at,
            "rows_sha256": self.rows_sha256,
            "server": {"version": get_version(), "commit": get_commit()},
        }


def citation_line(ds: dict) -> str:
    return f"Citation: {' '.join(str(ds.get('citation', '')).split())}"


ROUNDED_NOTE = (
    "Values are rounded here; the structured rows and pull.py have full "
    "precision."
)


def script_note(pull: Pull) -> list[str]:
    if not pull.request:
        return []
    return [
        "The structured result holds the request sent to the analytics API "
        "and `script`, a standalone pull.py that replays it and writes the "
        "rows to a CSV file."
    ]


def clamp_note(pull: Pull, start_date, end_date) -> list[str]:
    if not pull.clamped:
        return []
    return [
        "The date range was fitted to the dataset's coverage (requested "
        f"{start_date or 'start'} to {end_date or 'end'}). Tell the user."
    ]


async def run_pull(
    aoi_ids: list[str],
    dataset_id: int,
    start_date: Optional[str],
    end_date: Optional[str],
    context_layer: Optional[str],
    canopy_cover: Optional[int],
    change_over_time: bool,
) -> Pull:
    """Check and run a pull the way the agent's pull_data does; raise
    ToolError with a message for the model when it is refused or fails."""
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
    return Pull(
        ds=ds,
        areas=areas,
        start_date=plan.start_date,
        end_date=plan.end_date,
        clamped=plan.clamped,
        context_layer=context_layer,
        canopy_cover=canopy_cover,
        rows=rows,
        source_url=result.analytics_api_url,
        # A replayable request would hand out the rows a curated-only
        # dataset withholds, so it gets neither a request nor a pull.py.
        request=(
            None
            if is_curated_only(ds["dataset_id"])
            else result.analytics_api_request
        ),
        metadata=result.analytics_api_metadata,
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        rows_sha256=rows_digest(rows),
    )


async def pull_data(
    aoi_ids: AoiIds,
    dataset_id: DatasetId,
    start_date: StartDate = None,
    end_date: EndDate = None,
    context_layer: ContextLayer = None,
    canopy_cover: CanopyCover = None,
    change_over_time: ChangeOverTime = False,
) -> ToolResult:
    """Pull statistics for one or more areas from a dataset.

    Returns the numbers, with the areas, dates and options they are for.
    The date range is fitted to what the dataset covers, and the result says
    so when it was changed. Quote only the numbers this returns, and give
    the dataset's citation.
    """
    pull = await run_pull(
        aoi_ids,
        dataset_id,
        start_date,
        end_date,
        context_layer,
        canopy_cover,
        change_over_time,
    )
    rows = pull.rows
    lines = [
        f"{pull.heading()}: {len(rows)} rows.",
        *clamp_note(pull, start_date, end_date),
        await rows_text(rows, pull.ds["dataset_id"]),
        ROUNDED_NOTE,
        citation_line(pull.ds),
        *script_note(pull),
        "Quote only numbers shown here. Read the cautions with get_dataset "
        "before interpreting them.",
    ]
    return ToolResult(
        content="\n".join(lines),
        structured_content={
            **pull.provenance(),
            "row_count": len(rows),
            # A curated-only dataset's rows are never handed to a model.
            "rows": (
                []
                if is_curated_only(pull.ds["dataset_id"])
                else rows[:MAX_ROWS]
            ),
            "rows_truncated": len(rows) > MAX_ROWS,
            "script": pull_script(pull),
        },
    )
