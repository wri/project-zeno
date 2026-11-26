"""Curated charts first: the caption and the tool message of a curated chart.

`generate_insights(chart="standard")` shows a curated chart when the code
gate passes (src/api/services/charts/gate.py). No model writes about the
chart in the tool: the insight gets a fixed caption, and the tool message
gives the orchestrator the data and the facts to answer from
(docs/curated-charts-first-plan.md, sections 3 to 5).

`tool.py` imports this module lazily: the chart services import
`analyst.charts`, whose package init imports `tool.py`.
"""

import dataclasses
from collections import Counter
from typing import Optional, Sequence

from src.agent.datasets.curated_only import is_curated_only
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
from src.api.services.charts.view_facts import VIEW_FACTS
from src.api.services.charts.views import ChartView, get_view

# A chart with more rows than this gets its facts only (for example the
# alerts of each day of a long period).
MAX_MESSAGE_ROWS = 120

# Above this many areas, the caption and the header give the name of the
# selection ("47 Counties in Kenya") in place of every area name.
MAX_LISTED_AREAS = 10

# The areas with no value that a ranking fact names; above this it gives the
# count only.
MAX_ZERO_AREA_NAMES = 20

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


def _views(charts: Sequence[InsightChart]) -> list[ChartView]:
    views = (get_view(chart.view_id) for chart in charts if chart.view_id)
    return [view for view in views if view is not None]


def data_period(
    charts: Sequence[InsightChart], statistics: dict
) -> tuple[Optional[str], Optional[str]]:
    """The period of the data of the charts: the fixed period of their
    views when the dataset does not filter by date, else the pulled
    period. A forest flux pull for 2015 to 2020 still has the totals of
    2001 to 2025."""
    fixed = {view.fixed_period for view in _views(charts)}
    if len(fixed) == 1:
        period = next(iter(fixed))
        if period is not None:
            return period
    return statistics.get("start_date"), statistics.get("end_date")


def with_data_period(charts: Sequence[InsightChart], statistics: dict) -> dict:
    """`statistics` with the period of the data of the charts."""
    start, end = data_period(charts, statistics)
    return {**statistics, "start_date": start, "end_date": end}


def fill_missing_years(
    chart: InsightChart, start: Optional[str], end: Optional[str]
) -> InsightChart:
    """Add a row of 0 for each year of the pulled period that the chart
    has no row for, in year order. Only for a view with
    `zero_fill_years`: the API sends no row for a year without loss, and
    the generator drops rows of 0. Without these rows, the smallest value
    and the first and last year of the facts skip the years of 0."""
    view = get_view(chart.view_id) if chart.view_id else None
    if view is None or not view.zero_fill_years or not start or not end:
        return chart
    by_year: dict[int, dict] = {}
    for row in chart.chart_data:
        year = row.get(chart.x_axis)
        if year is None:
            return chart
        by_year[int(year)] = row
    columns = measures(chart)
    for year in range(int(start[:4]), int(end[:4]) + 1):
        if year not in by_year:
            by_year[year] = {
                chart.x_axis: year,
                **{column: 0 for column in columns},
            }
    chart.chart_data = [by_year[year] for year in sorted(by_year)]
    return chart


def _selection_name(statistics: dict) -> Optional[str]:
    """The name of the selection when there are too many areas to list;
    None when the areas are listed, or when an older pull has no name."""
    if len(statistics.get("aoi_names") or []) <= MAX_LISTED_AREAS:
        return None
    return statistics.get("aoi_selection_name") or None


def area_text(statistics: dict) -> str:
    """The areas of a pull for the tool message (English, model-facing):
    each name, or above `MAX_LISTED_AREAS` the name of the selection, or
    the count."""
    names = statistics.get("aoi_names") or []
    if len(names) <= MAX_LISTED_AREAS:
        return ", ".join(names)
    return _selection_name(statistics) or f"{len(names)} areas"


async def _area_label(statistics: dict, language: str) -> str:
    """The areas of a pull for the caption, in the reader's language."""
    names = statistics.get("aoi_names") or []
    if len(names) <= MAX_LISTED_AREAS:
        return ", ".join(names)
    return _selection_name(statistics) or await t(
        "analyst.curated_area_count", language, count=len(names)
    )


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
        "area": await _area_label(statistics, language),
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


def is_ranking(chart: InsightChart) -> bool:
    """True for the chart of a view that ranks several areas. Read from the
    view, not from the chart type: a restyled ranking keeps its view and
    its rows."""
    view = get_view(chart.view_id) if chart.view_id else None
    return view is not None and view.shape == "several_areas"


def _area_labels(rows: Sequence[dict]) -> list[str]:
    """The name of each ranked area; "name · parent" when the name repeats
    in the chart."""
    counts = Counter(row.get("name") for row in rows)
    return [
        f"{row.get('name')} · {row['parent']}"
        if counts[row.get("name")] > 1 and row.get("parent")
        else str(row.get("name"))
        for row in rows
    ]


def format_ranking_rows(chart: InsightChart) -> str:
    """The ranked areas as a table of rank, name, value and share (when the
    rows have it). The first `MAX_MESSAGE_ROWS` areas; a note counts the
    rest."""
    rows = chart.chart_data
    shown = rows[:MAX_MESSAGE_ROWS]
    with_share = any("share_pct" in row for row in shown)
    columns = ["rank", "name", _column_header(chart.y_axis)]
    if with_share:
        columns.append(_column_header("share_pct"))
    lines = [" | ".join(columns)]
    for label, row in zip(_area_labels(rows), shown):
        cells = [_cell(row.get("rank")), label, _cell(row.get(chart.y_axis))]
        if with_share:
            cells.append(_cell(row.get("share_pct")))
        lines.append(" | ".join(cells))
    rest = rows[len(shown) :]
    if rest:
        smaller = (rest[0].get(chart.y_axis) or 0) < (
            shown[-1].get(chart.y_axis) or 0
        )
        lines.append(
            f"{len(rest)} more areas, each with "
            f"{'less' if smaller else 'the same or less'}"
        )
    return "\n".join(lines)


def _areas(count: int) -> str:
    return f"{count} area" if count == 1 else f"{count} areas"


def ranking_fact_sentences(chart: InsightChart) -> list[str]:
    """The facts of a ranking of areas, from the rows of the chart: the
    number of areas, the total when the rows have shares, and the areas with
    a value of 0. A saved ranking gives the same facts on a recall."""
    rows = chart.chart_data
    measure = _column_header(chart.y_axis)
    sentences = [
        f"{_areas(len(rows))} ranked by {measure}, largest first. Areas "
        "with the same value share a rank."
    ]
    if rows and all("share_pct" in row for row in rows):
        total = round(sum(row.get(chart.y_axis) or 0 for row in rows), 2)
        sentences.append(
            f"Total over the {_areas(len(rows))}: {_cell(total)} "
            f"{unit_of(chart.y_axis)}. A share is the percent of this "
            "total."
        )
    else:
        sentences.append(
            "No total and no share are given: these areas may overlap, so "
            "a total over them could count the same ground twice."
        )
    labels = _area_labels(rows)
    zero = [
        label for label, row in zip(labels, rows) if not row.get(chart.y_axis)
    ]
    if zero:
        names = (
            f": {', '.join(zero)}" if len(zero) <= MAX_ZERO_AREA_NAMES else ""
        )
        sentences.append(
            f"{_areas(len(zero))} with a value of 0 for {measure}{names}."
        )
    return sentences


def format_rows(chart: InsightChart) -> str:
    """The rows of a chart as a table of the x axis and the measures, each
    value in full. A chart with too many rows gets a note in place of the
    table."""
    if is_ranking(chart):
        return format_ranking_rows(chart)
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
    # A view that pivots or renames the pulled columns draws them too.
    shown.update(
        column for view in _views(charts) for column in view.source_columns
    )
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
        f"Area: {area_text(statistics)}",
        f"Dataset: {statistics.get('dataset_name', '')}",
    ]
    start, end = data_period(charts, statistics)
    requested = (statistics.get("start_date"), statistics.get("end_date"))
    if (start, end) == requested:
        lines.append(f"Pulled period: {start} to {end}")
    else:
        lines += [
            f"Period of the data: {start} to {end}. This dataset does not "
            "filter by date.",
            f"Requested period: {requested[0]} to {requested[1]}. The "
            "figures are not for the requested period.",
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


def chart_fact_sentences(
    chart: InsightChart, rows: Sequence[dict] = ()
) -> list[str]:
    """The facts of a curated chart: the generic facts that are true for
    its view (`fact_kinds`, `fact_shares`), then the view's own facts from
    the pulled rows. A saved chart has no pulled rows: it gets the generic
    facts only."""
    if is_ranking(chart):
        return ranking_fact_sentences(chart)
    view = get_view(chart.view_id) if chart.view_id else None
    facts = measure_facts(chart)
    if view is not None and view.fact_kinds is not None:
        facts = [fact for fact in facts if fact.kind in view.fact_kinds]
    if view is not None and not view.fact_shares:
        facts = [dataclasses.replace(fact, share=None) for fact in facts]
    sentences = [fact.sentence for fact in facts]
    view_facts = VIEW_FACTS.get(chart.view_id or "")
    if view_facts is not None and rows:
        sentences += view_facts(list(rows))
    return sentences


def curated_facts_text(charts: Sequence[InsightChart]) -> str:
    """The facts of the curated charts (the charts of a view with
    `agent_enabled`) of a saved insight; "" when it has none. A curated insight's summary is a
    caption with no figures, so a recall or an update gives these."""
    lines: list[str] = []
    for chart in charts:
        view = get_view(chart.view_id) if chart.view_id else None
        # Only the released views. The LGMS views and the views of the
        # REST path also carry a view_id, but no model may read the
        # figures of a curated-only dataset.
        if (
            view is None
            or not view.agent_enabled
            or is_curated_only(chart.dataset_id)
        ):
            continue
        sentences = chart_fact_sentences(chart)
        if sentences:
            lines.append(f"Facts of {chart.title} (computed in code):")
            lines += [f"- {sentence}" for sentence in sentences]
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
        sentences = chart_fact_sentences(chart, rows)
        if sentences:
            lines += ["", f"Chart {index} facts (computed in code):"]
            lines += [f"- {sentence}" for sentence in sentences]
    if cautions:
        lines += ["", "Dataset cautions:", cautions.strip()]
    lines += ["", CURATED_ANSWER_INSTRUCTION]
    return "\n".join(lines)
