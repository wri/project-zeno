"""Natural and semi-natural grassland extent chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import GRASSLANDS_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class GrasslandsChartGenerator(ChartGenerator):
    """Grassland extent per year as a bar chart."""

    def __init__(self, dataset_id: int = GRASSLANDS_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

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
                title="Natural and Semi-Natural Grassland Extent by Year",
                chart_type="bar",
                x_axis="year",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
