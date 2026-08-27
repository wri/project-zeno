"""SBTN natural lands chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import NATURAL_LANDS_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class NaturalLandsChartGenerator(ChartGenerator):
    """Natural lands: area by class as a pie.

    A single-year (2020) snapshot, so the catalog rules out any time series.
    The analytics response carries one row per class with no `is_natural`
    flag, so the natural/non-natural split the catalog describes is left to
    the reader — the class names already carry it.
    """

    def __init__(self, dataset_id: int = NATURAL_LANDS_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = sorted(
            (row for row in rows if (row.get("area_ha") or 0) > 0),
            key=lambda row: row["area_ha"],
            reverse=True,
        )
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="Natural Lands Area by Class (2020)",
                chart_type="pie",
                x_axis="natural_lands_class",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
