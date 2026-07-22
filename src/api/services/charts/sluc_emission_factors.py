from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

# The API returns per-gas rows (CO2, CH4, N2O) plus their CO2e-equivalent
# total; only the total is tabled to avoid double counting.
TOTAL_GAS = "CO2e"


class SlucEmissionFactorsChartGenerator(ChartGenerator):
    """sLUC emission factors: per-crop deforestation emissions and emission
    factors as a table (catalog YAML default for multiple crops).

    Emissions are summed across the returned years; the emission factor is
    averaged instead — the YAML says to sum it, but factors are per-tonne
    annual rates and summing them across years would inflate them by the
    number of years.
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        emissions: dict[str, float] = {}
        factors: dict[str, List[float]] = {}
        for row in rows:
            if row.get("gas_type") != TOTAL_GAS:
                continue
            crop = str(row.get("crop_type"))
            emissions[crop] = emissions.get(crop, 0.0) + (
                row.get("emissions_tCO2e") or 0.0
            )
            factor = row.get("emissions_factor_tCO2e_per_tonne_production")
            if factor is not None:
                factors.setdefault(crop, []).append(factor)

        data = [
            {
                "crop": crop,
                "emissions_tCO2e": total,
                "avg_emission_factor_tCO2e_per_tonne": (
                    sum(factors[crop]) / len(factors[crop])
                    if factors.get(crop)
                    else None
                ),
            }
            for crop, total in sorted(
                emissions.items(), key=lambda item: item[1], reverse=True
            )
            if total != 0
        ]
        return [
            InsightChart(
                position=0,
                title="Deforestation Emissions by Agricultural Crop (tCO2e)",
                chart_type="table",
                chart_data=data,
            )
        ]
