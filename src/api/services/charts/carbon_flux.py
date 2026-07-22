from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

EMISSIONS = "Gross emissions"
REMOVALS = "Gross removals"
NET_FLUX = "Net flux"


class CarbonFluxChartGenerator(ChartGenerator):
    """Forest GHG net flux: emissions vs removals vs net as a diverging bar.

    The endpoint returns model-period totals (2001-2025) in one wide row
    per AOI; multi-AOI requests are summed into one set of totals. The API
    reports removals as a positive magnitude, so they are negated to sit
    below the axis, matching the sign convention of the net flux value
    (negative = net sink).
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        if not rows:
            return []
        emissions = sum(
            row.get("carbon_gross_emissions_Mg_CO2e") or 0.0 for row in rows
        )
        removals = sum(
            row.get("carbon_gross_removals_Mg_CO2e") or 0.0 for row in rows
        )
        net = sum(row.get("carbon_net_flux_Mg_CO2e") or 0.0 for row in rows)
        data = [
            {"flux": EMISSIONS, "MgCO2e": emissions},
            {"flux": REMOVALS, "MgCO2e": -removals},
            {"flux": NET_FLUX, "MgCO2e": net},
        ]
        return [
            InsightChart(
                position=0,
                title="Forest Greenhouse Gas Flux, 2001-2025 Total (MgCO2e)",
                chart_type="bar",
                x_axis="flux",
                y_axis="MgCO2e",
                chart_data=data,
            )
        ]
