from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import (
    ChartGenerator,
    drop_zero_rows,
    group_sum,
)


class LandCoverChartGenerator(ChartGenerator):
    """Global land cover: 2024 composition as a pie.

    The analyze path always queries the land_cover_composition endpoint
    (a 2024 snapshot), not the 2015→2024 change endpoint.
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        data = drop_zero_rows(
            group_sum(rows, "land_cover_class", "area_ha"), "area_ha"
        )
        return [
            InsightChart(
                position=0,
                title="Land Cover Composition, 2024 (ha)",
                chart_type="pie",
                x_axis="land_cover_class",
                y_axis="area_ha",
                chart_data=data,
            )
        ]
