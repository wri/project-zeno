"""Natural and semi-natural grassland extent chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import GRASSLANDS_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class GrasslandsChartGenerator(ChartGenerator):
    """Grassland extent per year as a bar chart."""

    dataset_id = GRASSLANDS_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = sorted(
            (row for row in rows if (row.get("area_ha") or 0) > 0),
            key=lambda row: row.get("year") or 0,
        )
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="charts.grasslands.by_year",
                chart_type="bar",
                x_axis="year",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
