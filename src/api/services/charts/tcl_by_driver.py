"""Tree cover loss by dominant driver chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_BY_DRIVER_ID,
)
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

UNKNOWN_DRIVER = "Unknown"


class TCLByDriverChartGenerator(ChartGenerator):
    """Tree cover loss area per driver as a pie, excluding unknown drivers."""

    def __init__(self, dataset_id: int = TREE_COVER_LOSS_BY_DRIVER_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = sorted(
            (
                row
                for row in rows
                if (row.get("area_ha") or 0) > 0
                and row.get("tree_cover_loss_driver") != UNKNOWN_DRIVER
            ),
            key=lambda row: row["area_ha"],
            reverse=True,
        )
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="Tree Cover Loss by Dominant Driver",
                chart_type="pie",
                x_axis="tree_cover_loss_driver",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
