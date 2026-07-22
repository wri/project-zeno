from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import (
    ChartGenerator,
    drop_zero_rows,
    sort_rows,
)


class TreeCoverChartGenerator(ChartGenerator):
    """Tree cover: total extent in the year-2000 snapshot.

    The analytics endpoint returns one total ``area_ha`` row per AOI (not
    the per-canopy-density bins the catalog YAML describes), so the chart
    is one bar per requested area, keyed by AOI name.
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        rows = drop_zero_rows(rows, "area_ha")
        return [
            InsightChart(
                position=0,
                title="Tree Cover Extent, 2000 (ha)",
                chart_type="bar",
                x_axis="name",
                y_axis="area_ha",
                chart_data=sort_rows(rows, "name"),
            )
        ]
