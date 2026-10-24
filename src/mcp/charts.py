"""Curated charts: the charts GNW itself draws for a dataset, over MCP.

The deterministic generators in `src/api/services/charts` turn pulled rows
into finished chart specs, for the REST `/api/analyze` route and for the
agent. Here they run on a pull of the client's choosing, and each chart
comes with its provenance: the pull it was drawn from, the generator that
drew it and that generator's source, so a client can show a trusted chart,
or read how GNW charts a dataset before drawing its own. No model is
involved.
"""

import inspect
import sys
from pathlib import Path
from typing import Optional

from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult

from src.agent.datasets.curated_only import (
    CURATED_ONLY_DATA_WITHHELD,
    is_curated_only,
)
from src.agent.datasets.palette import get_dataset_palette
from src.agent.subagents.analyst.charts import InsightChart
from src.agent.subagents.analyst.charts.color_resolver import (
    resolve_chart_colors,
)
from src.api.services.charts.base import ChartGenerator
from src.api.services.charts.curated import build_curated_charts
from src.api.services.charts.registry import DETERMINISTIC_GENERATORS
from src.mcp.data import (
    LANGUAGE,
    ROUNDED_NOTE,
    TEXT_CHAR_BUDGET,
    AoiIds,
    CanopyCover,
    ChangeOverTime,
    ContextLayer,
    DatasetId,
    EndDate,
    StartDate,
    citation_line,
    clamp_note,
    rows_text,
    run_pull,
    script_note,
)
from src.mcp.datasets import get_catalog_dataset
from src.mcp.script import pull_script
from src.shared.version import get_commit

REPO_URL = "https://github.com/wri/project-zeno/blob"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def find_generator(dataset_id: int) -> Optional[ChartGenerator]:
    return next(
        (g for g in DETERMINISTIC_GENERATORS if g.can_handle(dataset_id)),
        None,
    )


def curated_dataset_ids() -> set[int]:
    """The datasets with a curated chart generator."""
    return {generator.dataset_id for generator in DETERMINISTIC_GENERATORS}


def _generator_path(generator: ChartGenerator) -> str:
    path = Path(inspect.getfile(type(generator))).resolve()
    return path.relative_to(_REPO_ROOT).as_posix()


def generator_info(generator: ChartGenerator) -> dict:
    path = _generator_path(generator)
    return {
        "name": type(generator).__name__,
        "path": path,
        # At the commit the server runs, so the link shows the code that
        # drew the chart; at main when the commit is not known.
        "code_url": f"{REPO_URL}/{get_commit() or 'main'}/{path}",
        "description": inspect.getdoc(type(generator)) or "",
    }


def _no_generator(dataset_id: int) -> ToolError:
    ds = get_catalog_dataset(dataset_id)
    ids = ", ".join(str(i) for i in sorted(curated_dataset_ids()))
    return ToolError(
        f"GNW has no curated charts for {ds['dataset_name']}. Pull the data "
        "with pull_data and chart it as get_dataset's 'How to chart it' "
        f"says. Datasets with curated charts: {ids}."
    )


def _label_key(label: str) -> str:
    return " ".join(label.lower().replace("&", "and").split())


def _colors(chart: InsightChart, dataset_id: int) -> None:
    """Fill in the catalog colors a generator left unset.

    The shared builder leaves curated colors to the frontend
    (`curated.py`); a client has no frontend, so the colors come with the
    chart. A category is matched by its slug or its English label, which
    is what the analytics API returns ("Settlements and infrastructure" for
    the catalog's "Settlements & Infrastructure"). Colors a generator set
    itself stay.
    """
    if chart.color_map or chart.series_color:
        return
    resolve_chart_colors(chart, dataset_id)
    palette = get_dataset_palette(dataset_id)
    by_label = {
        _label_key(category["label_en"]): category["color"]
        for category in (palette["categories"] if palette else [])
    }
    # In the order the categories first appear in the rows.
    column = chart.color_field or chart.x_axis
    seen = dict.fromkeys(str(row.get(column)) for row in chart.chart_data)
    keys = [key for key in seen if key in chart.color_map]
    keys += sorted(set(chart.color_map) - set(keys))
    chart.color_map = {
        key: by_label.get(_label_key(key), chart.color_map[key])
        for key in keys
    }


def _chart_spec(chart: InsightChart) -> dict:
    return chart.model_dump(exclude={"insight"})


async def _chart_text(
    chart: InsightChart,
    withheld: bool,
    previous: list[InsightChart],
    budget: int,
) -> tuple[str, int]:
    """The chart's spec and rows as text, and the characters of rows used
    from `budget`, which all the charts of a result share."""
    fields = [
        f"type {chart.chart_type}",
        *(
            f"{name} {value}"
            for name, value in (
                ("x", chart.x_axis),
                ("y", chart.y_axis),
                ("color by", chart.color_field),
                ("stack by", chart.stack_field),
                ("group by", chart.group_field),
                ("series", ", ".join(chart.series_fields)),
            )
            if value
        ),
    ]
    lines = [f"## {chart.position + 1}. {chart.title} ({'; '.join(fields)})"]
    used = 0
    same = next(
        (other for other in previous if other.chart_data == chart.chart_data),
        None,
    )
    if withheld:
        lines.append(CURATED_ONLY_DATA_WITHHELD)
    elif same is not None:
        lines.append(f"The rows of chart {same.position + 1}.")
    else:
        text = await rows_text(
            chart.chart_data, chart.dataset_id or 0, budget=budget
        )
        lines.append(text)
        used = len(text)
    if chart.color_map:
        lines.append(
            "Colors: "
            + ", ".join(
                f"{key} {value}" for key, value in chart.color_map.items()
            )
        )
    elif chart.series_color:
        lines.append(f"Color: {chart.series_color}")
    return "\n".join(lines), used


async def curated_charts(
    aoi_ids: AoiIds,
    dataset_id: DatasetId,
    start_date: StartDate = None,
    end_date: EndDate = None,
    context_layer: ContextLayer = None,
    canopy_cover: CanopyCover = None,
    change_over_time: ChangeOverTime = False,
) -> ToolResult:
    """Get GNW's own curated charts for one or more areas and a dataset.

    Pulls the data as pull_data does and draws the charts Global Nature
    Watch shows for the dataset, with code GNW maintains: chart specs with
    their data and colors, the pull they come from, and the generator that
    drew them (get_chart_code shows its source). Prefer these to charts of
    your own when the user wants the standard view of a dataset; list_datasets
    says which datasets have them.
    """
    generator = _generator_or_refuse(dataset_id)
    pull = await run_pull(
        aoi_ids,
        dataset_id,
        start_date,
        end_date,
        context_layer,
        canopy_cover,
        change_over_time,
    )
    charts = await build_curated_charts(
        dataset_id, pull.rows, LANGUAGE, [generator]
    )
    withheld = is_curated_only(dataset_id)
    for chart in charts:
        _colors(chart, dataset_id)
        if withheld:
            # A curated-only dataset's values are never handed to a model.
            chart.chart_data = []

    info = generator_info(generator)
    lines = [
        f"GNW's curated charts: {pull.heading()}.",
        *clamp_note(pull, start_date, end_date),
    ]
    if charts:
        budget = TEXT_CHAR_BUDGET
        for i, chart in enumerate(charts):
            text, used = await _chart_text(
                chart, withheld, charts[:i], max(budget, 0)
            )
            lines.append(text)
            budget -= used
        if not withheld:
            lines.append(ROUNDED_NOTE)
    else:
        lines.append("The pull returned no data to chart.")
    lines.extend(
        [
            f"Drawn by {info['name']} ({info['code_url']}); get_chart_code "
            "shows its source.",
            citation_line(pull.ds),
            *script_note(pull),
        ]
    )
    return ToolResult(
        content="\n\n".join(lines),
        structured_content={
            **pull.provenance(),
            "curated": True,
            "generator": info,
            "charts": [_chart_spec(chart) for chart in charts],
            "script": pull_script(pull),
        },
    )


def _generator_or_refuse(dataset_id: int) -> ChartGenerator:
    get_catalog_dataset(dataset_id)
    generator = find_generator(dataset_id)
    if generator is None:
        raise _no_generator(dataset_id)
    return generator


def _source(generator: ChartGenerator) -> str:
    """The source of the module that holds `generator`."""
    return inspect.getsource(sys.modules[type(generator).__module__])


async def get_chart_code(dataset_id: DatasetId) -> ToolResult:
    """Read the code GNW draws a dataset's curated charts with.

    The generator turns the rows pull_data returns into the chart specs
    curated_charts returns: which rows it keeps, how it sorts and sums
    them, and which chart types and axes it uses. Read it to chart the
    dataset the way GNW does, or to explain a curated chart. The helpers it
    imports are in src/api/services/charts/base.py.
    """
    generator = _generator_or_refuse(dataset_id)
    info = generator_info(generator)
    source = _source(generator)
    return ToolResult(
        content=f"# {info['path']} ({info['code_url']})\n\n{source}",
        structured_content={**info, "source": source},
    )


def chart_code_resource(dataset_id: int) -> str:
    """The source of a dataset's curated chart generator."""
    return _source(_generator_or_refuse(dataset_id))
