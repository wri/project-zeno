"""Tree cover gain chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_GAIN_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class TreeCoverGainChartGenerator(ChartGenerator):
    """Tree cover gain per reporting period as a bar chart."""

    dataset_id = TREE_COVER_GAIN_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = sorted(
            (row for row in rows if (row.get("area_ha") or 0) > 0),
            key=lambda row: row.get("tree_cover_gain_period") or "",
        )
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="charts.tree_cover_gain.by_period",
                chart_type="bar",
                x_axis="tree_cover_gain_period",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
