"""SBTN natural lands chart generator."""

from typing import List

from _gnw import NATURAL_LANDS_ID
from _gnw import InsightChart
from base import ChartGenerator, by_area_desc


class NaturalLandsChartGenerator(ChartGenerator):
    """Natural lands area by class as a pie, largest class first."""

    dataset_id = NATURAL_LANDS_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = by_area_desc(rows)
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="charts.natural_lands.by_class",
                chart_type="pie",
                x_axis="natural_lands_class",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
