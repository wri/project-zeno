from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class TCLChartGenerator(ChartGenerator):
    """Tree Cover Loss: annual loss area + annual GHG emissions, as two bars."""

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        rows = [r for r in rows if r.get("area_ha") != 0]
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
