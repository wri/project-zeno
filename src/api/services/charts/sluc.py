"""Deforestation sLUC emission factors chart generator."""

from collections import defaultdict
from typing import List

from src.agent.datasets.handlers.analytics_handler import (
    SLUC_EMISSION_FACTORS_ID,
)
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

# CO2e is the sum of the other gases, so including it would double-count.
CO2_EQUIVALENT = "CO2e"


class SlucEmissionFactorsChartGenerator(ChartGenerator):
    """Emissions by gas type as a pie, plus emissions by crop as a table."""

    dataset_id = SLUC_EMISSION_FACTORS_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = [
            row
            for row in rows
            if (row.get("emissions_tCO2e") or 0) > 0
            and row.get("gas_type") not in (None, CO2_EQUIVALENT)
            and row.get("crop_type") is not None
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
                title="charts.sluc.by_gas",
                chart_type="pie",
                x_axis="gas_type",
                y_axis="emissions_tCO2e",
                chart_data=descending(by_gas, "gas_type"),
            ),
            InsightChart(
                position=1,
                title="charts.sluc.by_crop",
                chart_type="table",
                chart_data=descending(by_crop, "crop_type"),
            ),
        ]
