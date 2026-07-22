from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import (
    ChartGenerator,
    drop_zero_rows,
    sort_rows,
)

# Renamed per the catalog YAML so the chart legend reads as prose; the raw
# analytics column names are not user-facing.
FIRES_SERIES = "Tree cover loss due to fires"
OTHER_SERIES = "All other tree cover loss"


class TCLFiresChartGenerator(ChartGenerator):
    """Tree cover loss due to fires: fire vs. non-fire loss stacked per year.

    Emissions are never shown for this dataset (catalog YAML rule).
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        rows = sort_rows(
            drop_zero_rows(rows, "area_ha"), "tree_cover_loss_year"
        )
        data = [
            {
                "tree_cover_loss_year": row["tree_cover_loss_year"],
                FIRES_SERIES: row.get("tree_cover_loss_from_fires_area_ha")
                or 0.0,
                OTHER_SERIES: row.get("tree_cover_loss_non_fires_area_ha")
                or 0.0,
            }
            for row in rows
        ]
        return [
            InsightChart(
                position=0,
                title="Annual Tree Cover Loss: Fires vs. Other Causes (ha)",
                chart_type="stacked-bar",
                x_axis="tree_cover_loss_year",
                series_fields=[FIRES_SERIES, OTHER_SERIES],
                chart_data=data,
            )
        ]
