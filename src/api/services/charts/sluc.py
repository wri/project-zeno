"""Deforestation sLUC emission factors chart generator."""

from collections import defaultdict
from typing import List

from src.agent.datasets.handlers.analytics_handler import (
    SLUC_EMISSION_FACTORS_ID,
)
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

# The API reports CO2e alongside the individual gases, but it is exactly
# their sum, not a fourth gas. Dropping it avoids double-counting in the pie
# and leaves the per-crop totals unchanged.
CO2_EQUIVALENT = "CO2e"


class SlucEmissionFactorsChartGenerator(ChartGenerator):
    """sLUC emission factors: emissions by gas type and by crop.

    The response spans every crop, gas and year for the AOI, so the two
    charts the catalog names are both built: a gas-type pie (the proportional
    split across CO2, CH4 and N2O) and a per-crop table of CO2e totals.
    Emission factors are per tonne of production and so are never summed
    here — only emissions are.
    """

    def __init__(self, dataset_id: int = SLUC_EMISSION_FACTORS_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = [
            row
            for row in rows
            if (row.get("emissions_tCO2e") or 0) > 0
            and row.get("gas_type") != CO2_EQUIVALENT
        ]
        if not present:
            return []

        by_gas: dict[str, float] = defaultdict(float)
        by_crop: dict[str, float] = defaultdict(float)
        for row in present:
            by_gas[row["gas_type"]] += row["emissions_tCO2e"]
            by_crop[row["crop_type"]] += row["emissions_tCO2e"]

        def descending(totals: dict[str, float], key: str) -> List[dict]:
            return [
                {key: name, "emissions_tCO2e": total}
                for name, total in sorted(
                    totals.items(), key=lambda item: item[1], reverse=True
                )
            ]

        return [
            InsightChart(
                position=0,
                title="Deforestation Emissions by Gas Type (tCO2e)",
                chart_type="pie",
                x_axis="gas_type",
                y_axis="emissions_tCO2e",
                chart_data=descending(by_gas, "gas_type"),
            ),
            InsightChart(
                position=1,
                title="Deforestation Emissions by Crop (tCO2e)",
                chart_type="table",
                chart_data=descending(by_crop, "crop_type"),
            ),
        ]
