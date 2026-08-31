"""Forest greenhouse gas net flux chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import FOREST_CARBON_FLUX_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class ForestFluxChartGenerator(ChartGenerator):
    """Gross emissions, gross removals and net flux as a diverging bar
    chart, with removals drawn below the axis."""

    dataset_id = FOREST_CARBON_FLUX_ID
    label_fields = ("flux",)

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        fields = (
            "carbon_gross_emissions_Mg_CO2e",
            "carbon_gross_removals_Mg_CO2e",
            "carbon_net_flux_Mg_CO2e",
        )
        if not any(row.get(f) is not None for row in rows for f in fields):
            return []

        emissions, removals, net = (
            sum(row.get(f) or 0 for row in rows) for f in fields
        )

        return [
            InsightChart(
                position=0,
                title="charts.forest_flux.net",
                chart_type="bar",
                x_axis="flux",
                y_axis="carbon_MgCO2e",
                chart_data=[
                    {
                        "flux": "charts.label.gross_emissions",
                        "carbon_MgCO2e": emissions,
                    },
                    {
                        "flux": "charts.label.gross_removals",
                        "carbon_MgCO2e": -removals,
                    },
                    {"flux": "charts.label.net_flux", "carbon_MgCO2e": net},
                ],
            )
        ]
