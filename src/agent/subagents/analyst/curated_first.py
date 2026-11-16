"""Curated charts first: the caption and the tool message of a curated chart.

`generate_insights(chart="standard")` shows a curated chart when the code
gate passes (src/api/services/charts/gate.py). No model writes about the
chart in the tool: the insight gets a fixed caption, and the tool message
gives the orchestrator the data and the facts to answer from
(docs/curated-charts-first-plan.md, sections 3 to 5).

`tool.py` imports this module lazily: the chart services import
`analyst.charts`, whose package init imports `tool.py`.
"""

from typing import Callable, Optional, Sequence

from src.agent.datasets.handlers.analytics_handler import (
    canopy_cover_threshold,
)
from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.curated import (
    context_layer_label,
    dataset_context_layer,
)
from src.api.services.charts.facts import (
    is_time_axis,
    measure_facts,
    unit_of,
)
from src.api.services.charts.gate import measures
from src.api.services.charts.tcl_by_driver import driver_facts
from src.api.services.charts.views import get_view

# Facts of a view that its chart cannot give, from the pulled rows: for
# example a class that the chart leaves out.
VIEW_FACTS: dict[str, Callable[[list[dict]], list[str]]] = {
    "tcl_by_driver.by_driver": driver_facts,
}

# A chart with more rows than this gets its facts only (for example the
# alerts of each day of a long period).
MAX_MESSAGE_ROWS = 120

# Model-facing, so English like the other tool instructions. The last part
# of the tool message of a curated chart.
CURATED_ANSWER_INSTRUCTION = (
    "How to answer:\n"
    "- Answer the question of the user from the figures above. Copy the "
    "figures with their units. Do not calculate new figures: no averages, "
    "no medians, no rates per year, no sums or differences over a part of "
    "the pulled period, and no percentages that the facts do not give.\n"
    "- If the pulled period is not the period that the user asked for, "
    "say so. Give the figures of the pulled period. Do not add or remove "
    "years yourself.\n"
    "- If the figures above do not answer the question, do not give an "
    "answer that they do not support. Tell the user what the chart shows, "
    "and tell them that they can ask for more detail or for a custom "
    "chart.\n"
    "- State the period, the context layer and the canopy cover threshold "
    "that the figures apply to. Name only the context layer of the header "
    "above. If the user asked for a context layer that the header does not "
    "give, tell them that these figures are not for that layer.\n"
    '- Call generate_insights with chart="custom" only when the user asks '
    "for something that the standard chart does not have. Do not call it "
    "now for this question."
)


def period_label(start: Optional[str], end: Optional[str]) -> str:
    """The pulled period: years when it runs from 1 January to 31 December,
    else the dates."""
    if not start or not end:
        return f"{start or '?'} – {end or '?'}"
    if start[5:] == "01-01" and end[5:] == "12-31":
        first, last = start[:4], end[:4]
        return first if first == last else f"{first}–{last}"
    return f"{start} – {end}"


async def curated_caption(statistics: dict, language: str) -> str:
    """The fixed caption of a curated insight: the dataset, the area, the
    period, the context layer and the canopy cover threshold. No figures."""
    language = language or DEFAULT_LANGUAGE
    filters = []
    layer = await context_layer_label(
        dataset_context_layer(
            statistics.get("dataset_id"), statistics.get("context_layer")
        ),
        language,
    )
    if layer:
        filters.append(layer)
    threshold = canopy_cover_threshold(
        statistics.get("dataset_id"),
        statistics.get("context_layer"),
        statistics.get("parameters"),
    )
    if threshold is not None:
        filters.append(
            await t(
                "analyst.filter_canopy_cover", language, threshold=threshold
            )
        )
    values = {
        "dataset_name": statistics.get("dataset_name", ""),
        "area": ", ".join(statistics.get("aoi_names") or []),
        "period": period_label(
            statistics.get("start_date"), statistics.get("end_date")
        ),
    }
    if filters:
        return await t(
            "analyst.curated_caption_filtered",
            language,
            filters=", ".join(filters),
            **values,
        )
    return await t("analyst.curated_caption", language, **values)


def _cell(value) -> str:
    """A value at full precision: no rounding, no truncation."""
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _column_header(column: str) -> str:
    unit = unit_of(column)
    return f"{column} ({unit})" if unit else column


def format_rows(chart: InsightChart) -> str:
    """The rows of a chart as a table of the x axis and the measures, each
    value in full. A chart with too many rows gets a note in place of the
    table."""
    columns = [chart.x_axis, *measures(chart)]
    if len(chart.chart_data) > MAX_MESSAGE_ROWS:
        return (
            f"{len(chart.chart_data)} rows; too many to list. Use the facts."
        )
    lines = [" | ".join(_column_header(column) for column in columns)]
    for row in chart.chart_data:
        lines.append(" | ".join(_cell(row.get(c)) for c in columns))
    return "\n".join(lines)


def covered_x(charts: Sequence[InsightChart]) -> Optional[str]:
    """The first and the last x value with data, over the charts with a time
    axis; None when no chart has a time axis."""
    values = sorted(
        {
            _cell(row.get(chart.x_axis))
            for chart in charts
            if is_time_axis(chart)
            for row in chart.chart_data
            if any(row.get(m) is not None for m in measures(chart))
        }
    )
    if not values:
        return None
    return values[0] if len(values) == 1 else f"{values[0]} to {values[-1]}"


def unshown_columns(
    rows: Sequence[dict], charts: Sequence[InsightChart]
) -> list[str]:
    """The columns of the pulled rows that have a value and that no chart
    has, in pull order. A column with no value in any row is left out: it
    has no data to offer."""
    shown = {
        column
        for chart in charts
        for row in chart.chart_data
        for column in row
    }
    pulled = dict.fromkeys(
        column
        for row in rows
        for column, value in row.items()
        if value is not None
    )
    return [column for column in pulled if column not in shown]


def _header(
    charts: Sequence[InsightChart],
    statistics: dict,
    caption: str,
    other_columns: Sequence[str] = (),
) -> list[str]:
    threshold = canopy_cover_threshold(
        statistics.get("dataset_id"),
        statistics.get("context_layer"),
        statistics.get("parameters"),
    )
    context_layer = dataset_context_layer(
        statistics.get("dataset_id"), statistics.get("context_layer")
    )
    lines = [
        f"Standard charts shown to the user: {len(charts)}. These are "
        "curated charts; no model wrote them.",
    ]
    for index, chart in enumerate(charts, 1):
        lines.append(f"Chart {index}: {chart.title} (view {chart.view_id})")
        view = get_view(chart.view_id) if chart.view_id else None
        if view is not None and view.agent_note:
            lines.append(f"Chart {index} note: {view.agent_note}")
    lines += [
        "",
        f"Area: {', '.join(statistics.get('aoi_names') or [])}",
        f"Dataset: {statistics.get('dataset_name', '')}",
        f"Pulled period: {statistics.get('start_date')} to "
        f"{statistics.get('end_date')}",
    ]
    covered = covered_x(charts)
    if covered is not None:
        lines.append(f"Years or dates with data in the rows: {covered}")
    lines.append(
        f"Context layer: {context_layer.replace('_', ' ')}"
        if context_layer
        else "Context layer: none (all of the area)"
    )
    if threshold is not None:
        lines.append(f"Canopy cover threshold: {threshold}%")
    if other_columns:
        lines.append(
            "Columns of the pulled data that no chart shows: "
            + ", ".join(other_columns)
        )
    lines.append(f"Caption shown under the chart: {caption}")
    return lines


def curated_facts_text(charts: Sequence[InsightChart]) -> str:
    """The facts of the curated charts (the charts with a `view_id`) of a
    saved insight; "" when it has none. A curated insight's summary is a
    caption with no figures, so a recall or an update gives these."""
    lines: list[str] = []
    for chart in charts:
        if not chart.view_id:
            continue
        facts = measure_facts(chart)
        if facts:
            lines.append(f"Facts of {chart.title} (computed in code):")
            lines += [f"- {fact.sentence}" for fact in facts]
    return "\n".join(lines)


def build_curated_tool_message(
    charts: Sequence[InsightChart],
    statistics: dict,
    caption: str,
    cautions: Optional[str] = None,
    other_columns: Sequence[str] = (),
    rows: Sequence[dict] = (),
) -> str:
    """The tool message of a curated chart: the header, the rows of each
    chart in full, the facts with units, the dataset cautions, and the
    instruction for the answer. `other_columns` are the pulled columns
    that no chart shows; the header names them. `rows` are the pulled
    rows, for the facts of a view that its chart cannot give."""
    lines = _header(charts, statistics, caption, other_columns)
    for index, chart in enumerate(charts, 1):
        lines += ["", f"Chart {index} rows:", format_rows(chart)]
        sentences = [fact.sentence for fact in measure_facts(chart)]
        view_facts = VIEW_FACTS.get(chart.view_id or "")
        if view_facts is not None:
            sentences += view_facts(list(rows))
        if sentences:
            lines += ["", f"Chart {index} facts (computed in code):"]
            lines += [f"- {sentence}" for sentence in sentences]
    if cautions:
        lines += ["", "Dataset cautions:", cautions.strip()]
    lines += ["", CURATED_ANSWER_INSTRUCTION]
    return "\n".join(lines)
