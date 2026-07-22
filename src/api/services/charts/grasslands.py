from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import (
    ChartGenerator,
    drop_zero_rows,
    sort_rows,
)


class GrasslandsChartGenerator(ChartGenerator):
    """Grasslands: annual natural/semi-natural grassland extent as a line."""

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        rows = sort_rows(drop_zero_rows(rows, "area_ha"), "year")
        return [
            InsightChart(
                position=0,
                title="Natural and Semi-Natural Grassland Extent (ha)",
                chart_type="line",
                x_axis="year",
                y_axis="area_ha",
                chart_data=rows,
            )
        ]
