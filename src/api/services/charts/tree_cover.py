"""Tree cover extent chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class TreeCoverChartGenerator(ChartGenerator):
    """Tree cover extent per area of interest as a bar chart."""

    def __init__(self, dataset_id: int = TREE_COVER_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = sorted(
            (row for row in rows if (row.get("area_ha") or 0) > 0),
            key=lambda row: row["area_ha"],
            reverse=True,
        )
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="Tree Cover Extent",
                chart_type="bar",
                x_axis="name",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
