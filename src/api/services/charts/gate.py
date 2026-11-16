"""The code gate for a curated chart in the agent.

`generate_insights` shows a curated chart in place of a chart from the code
executor only when the gate passes (docs/curated-charts-first-plan.md,
section 2). The model cannot change the result of the gate. When the gate
fails, the tool runs the code executor as before.

A pull passes when:

- the dataset has a view with `agent_enabled`;
- the number of areas in the rows agrees with the `shape` of the view;
- the generator returns a chart with data (see `charts_with_data`).
"""

from dataclasses import dataclass
from typing import Iterable, Optional

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.views import ChartView, agent_views, get_view

# The columns that name the area of a row, in order of preference.
AREA_COLUMNS = ("aoi_id", "name")


@dataclass(frozen=True)
class GateResult:
    passed: bool
    # Why the gate failed, for the logs. Empty when it passed.
    reason: str = ""
    # The views that can show the pull, when the gate passed.
    views: tuple[ChartView, ...] = ()

    @property
    def title_keys(self) -> list[str]:
        return [view.title_key for view in self.views]


def count_areas(rows: Iterable[dict], default: int) -> int:
    """The number of different areas in the rows. `default` when no row
    names its area."""
    rows = list(rows)
    for column in AREA_COLUMNS:
        areas = {row[column] for row in rows if row.get(column) is not None}
        if areas:
            return len(areas)
    return default


def shape_fits(view: ChartView, area_count: int) -> bool:
    if view.shape == "one_area":
        return area_count == 1
    return area_count >= 1


def view_gate(dataset_id: Optional[int], area_count: int) -> GateResult:
    """The part of the gate that needs no chart: an enabled view whose
    shape agrees with the number of areas."""
    views = agent_views(dataset_id) if dataset_id is not None else []
    if not views:
        return GateResult(False, f"no agent view for dataset {dataset_id}")
    fitting = tuple(view for view in views if shape_fits(view, area_count))
    if not fitting:
        return GateResult(
            False,
            f"{area_count} areas do not fit the views "
            f"{[view.id for view in views]}",
        )
    return GateResult(True, views=fitting)


def measures(chart: InsightChart) -> list[str]:
    """The value columns of a chart: its series, or its y axis."""
    return list(chart.series_fields) if chart.series_fields else [chart.y_axis]


def has_data(chart: InsightChart) -> bool:
    """True when at least one row has a value. A metric that the API does
    not compute arrives as a null in each row, for example the emissions
    of natural forest below a 30% canopy threshold."""
    columns = measures(chart)
    return any(
        row.get(column) is not None
        for row in chart.chart_data
        for column in columns
    )


def charts_with_data(charts: Iterable[InsightChart]) -> list[InsightChart]:
    """The charts of agent views that have data, renumbered from 0."""
    kept: list[InsightChart] = []
    for chart in charts:
        view = get_view(chart.view_id) if chart.view_id else None
        if view is None or not view.agent_enabled or not has_data(chart):
            continue
        chart.position = len(kept)
        kept.append(chart)
    return kept
