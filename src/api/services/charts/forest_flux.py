"""Forest greenhouse gas net flux chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import FOREST_CARBON_FLUX_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class ForestFluxChartGenerator(ChartGenerator):
    """Gross emissions, gross removals and net flux as a diverging bar
    chart, with removals drawn below the axis."""

    def __init__(self, dataset_id: int = FOREST_CARBON_FLUX_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        if not rows:
            return []
        row = rows[0]
        emissions = row.get("carbon_gross_emissions_Mg_CO2e")
        removals = row.get("carbon_gross_removals_Mg_CO2e")
        net = row.get("carbon_net_flux_Mg_CO2e")
        if emissions is None and removals is None and net is None:
            return []

        return [
            InsightChart(
                position=0,
                title="Forest Greenhouse Gas Net Flux, 2001-2025 Total",
                chart_type="bar",
                x_axis="flux",
                y_axis="carbon_MgCO2e",
                chart_data=[
                    {
                        "flux": "Gross emissions",
                        "carbon_MgCO2e": emissions,
                    },
                    {
                        "flux": "Gross removals",
                        "carbon_MgCO2e": (
                            -removals if removals is not None else None
                        ),
                    },
                    {"flux": "Net flux", "carbon_MgCO2e": net},
                ],
            )
        ]
