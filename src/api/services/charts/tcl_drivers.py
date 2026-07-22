from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import (
    ChartGenerator,
    drop_zero_rows,
    group_sum,
)

# Excluded from the driver breakdown per the catalog YAML.
UNKNOWN_DRIVER = "Unknown"


class TCLDriversChartGenerator(ChartGenerator):
    """Tree cover loss by dominant driver: full-period area per driver as a
    pie. This dataset is a single-period aggregate — no timeseries."""

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        rows = [
            row
            for row in rows
            if row.get("tree_cover_loss_driver") != UNKNOWN_DRIVER
        ]
        data = drop_zero_rows(
            group_sum(rows, "tree_cover_loss_driver", "area_ha"), "area_ha"
        )
        return [
            InsightChart(
                position=0,
                title="Tree Cover Loss by Dominant Driver (ha)",
                chart_type="pie",
                x_axis="tree_cover_loss_driver",
                y_axis="area_ha",
                chart_data=data,
            )
        ]
