"""Tree cover extent chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator, by_area_desc


class TreeCoverChartGenerator(ChartGenerator):
    """Tree cover extent per area of interest as a bar chart."""

    dataset_id = TREE_COVER_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = by_area_desc(rows)
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="charts.tree_cover.extent",
                chart_type="bar",
                x_axis="name",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
