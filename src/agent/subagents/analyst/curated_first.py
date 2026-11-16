"""Curated charts first: the caption and the tool message of a curated chart.

`generate_insights(chart="standard")` shows a curated chart when the code
gate passes (src/api/services/charts/gate.py). No model writes about the
chart in the tool: the insight gets a fixed caption, and the tool message
gives the orchestrator the data and the facts to answer from
(docs/curated-charts-first-plan.md, sections 3 to 5).

`tool.py` imports this module lazily: the chart services import
`analyst.charts`, whose package init imports `tool.py`.
"""

from typing import Optional, Sequence

from src.agent.datasets.handlers.analytics_handler import (
    canopy_cover_threshold,
)
from src.agent.i18n import MESSAGES, t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.facts import (
    is_time_axis,
    measure_facts,
    unit_of,
)
from src.api.services.charts.gate import measures

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


def context_layer_key(context_layer: str) -> str:
    return f"context_layer.{context_layer}"


async def context_layer_label(
    context_layer: Optional[str], language: str
) -> Optional[str]:
    """The name of a context layer in `language`; the raw value without
    underscores when it has no message."""
    if not context_layer:
        return None
    key = context_layer_key(context_layer)
    if key in MESSAGES:
        return await t(key, language)
    return context_layer.replace("_", " ")


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
        statistics.get("context_layer"), language
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


def _header(
    charts: Sequence[InsightChart], statistics: dict, caption: str
) -> list[str]:
    context_layer = statistics.get("context_layer")
    threshold = canopy_cover_threshold(
        statistics.get("dataset_id"),
        context_layer,
        statistics.get("parameters"),
    )
    lines = [
        f"Standard charts shown to the user: {len(charts)}. These are "
        "curated charts; no model wrote them.",
    ]
    for index, chart in enumerate(charts, 1):
        lines.append(f"Chart {index}: {chart.title} (view {chart.view_id})")
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
    lines.append(f"Caption shown under the chart: {caption}")
    return lines


def build_curated_tool_message(
    charts: Sequence[InsightChart],
    statistics: dict,
    caption: str,
    cautions: Optional[str] = None,
) -> str:
    """The tool message of a curated chart: the header, the rows of each
    chart in full, the facts with units, the dataset cautions, and the
    instruction for the answer."""
    lines = _header(charts, statistics, caption)
    for index, chart in enumerate(charts, 1):
        lines += ["", f"Chart {index} rows:", format_rows(chart)]
        facts = measure_facts(chart)
        if facts:
            lines += ["", f"Chart {index} facts (computed in code):"]
            lines += [f"- {fact.sentence}" for fact in facts]
    if cautions:
        lines += ["", "Dataset cautions:", cautions.strip()]
    lines += ["", CURATED_ANSWER_INSTRUCTION]
    return "\n".join(lines)
