from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import (
    ChartGenerator,
    drop_zero_rows,
    group_sum,
)

# SBTN classes counted as non-natural: every class whose name carries a
# "non-natural" qualifier (e.g. "Non-natural tree cover", "Wetland
# non-natural short vegetation") plus the two unqualified human land uses.
# Everything else (Natural forests, Mangroves, Bare, Natural water, ...) is
# natural per the SBTN map definition.
NON_NATURAL_CLASSES = {"Cropland", "Built-up"}


def _category(natural_lands_class: str) -> str:
    is_non_natural = (
        "non-natural" in natural_lands_class.lower()
        or natural_lands_class in NON_NATURAL_CLASSES
    )
    return "Non-natural" if is_non_natural else "Natural"


class NaturalLandsChartGenerator(ChartGenerator):
    """SBTN Natural Lands: natural vs non-natural area in the 2020 snapshot,
    as a two-slice pie (catalog YAML rule)."""

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        categorized = [
            {
                "category": _category(str(row.get("natural_lands_class"))),
                "area_ha": row.get("area_ha"),
            }
            for row in rows
        ]
        data = drop_zero_rows(
            group_sum(categorized, "category", "area_ha"), "area_ha"
        )
        return [
            InsightChart(
                position=0,
                title="Natural vs Non-Natural Land, 2020 (ha)",
                chart_type="pie",
                x_axis="category",
                y_axis="area_ha",
                chart_data=data,
            )
        ]
