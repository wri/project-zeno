"""Tree Cover Loss chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_LOSS_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class TCLChartGenerator(ChartGenerator):
    """Tree Cover Loss: annual loss area + annual GHG emissions, as two bars."""

    def __init__(self, dataset_id: int = TREE_COVER_LOSS_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        # The analytics API returns rows in arbitrary order; sort by year so
        # the chart's category x-axis reads 2001 → 2025 rather than a shuffle.
        rows = sorted(
            (r for r in rows if r.get("area_ha") != 0),
            key=lambda r: r.get("tree_cover_loss_year") or 0,
        )
        return [
            InsightChart(
                position=0,
                title="Annual Tree Cover Loss",
                chart_type="bar",
                x_axis="tree_cover_loss_year",
                y_axis="area_ha",
                chart_data=rows,
            ),
            InsightChart(
                position=1,
                title="Annual GHG Emissions from Tree Cover Loss",
                chart_type="bar",
                x_axis="tree_cover_loss_year",
                y_axis="carbon_emissions_MgCO2e",
                chart_data=rows,
            ),
        ]
