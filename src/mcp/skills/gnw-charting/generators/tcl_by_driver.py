"""Tree cover loss by dominant driver chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_BY_DRIVER_ID,
)
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator, by_area_desc

UNKNOWN_DRIVER = "Unknown"


class TCLByDriverChartGenerator(ChartGenerator):
    """Tree cover loss area per driver as a pie, excluding unknown drivers."""

    dataset_id = TREE_COVER_LOSS_BY_DRIVER_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = by_area_desc(
            row
            for row in rows
            if row.get("tree_cover_loss_driver") != UNKNOWN_DRIVER
        )
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="charts.tcl_by_driver.by_driver",
                chart_type="pie",
                x_axis="tree_cover_loss_driver",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
