from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import (
    ChartGenerator,
    drop_zero_rows,
    sort_rows,
)


class TreeCoverGainChartGenerator(ChartGenerator):
    """Tree cover gain: area per five-year period as bars.

    The analytics API returns disjoint five-year periods ("2000-2005",
    "2005-2010", ...), not the cumulative-to-2020 periods the catalog YAML
    describes; the period labels are plotted as returned.
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        rows = sort_rows(
            drop_zero_rows(rows, "area_ha"), "tree_cover_gain_period"
        )
        return [
            InsightChart(
                position=0,
                title="Tree Cover Gain by Period (ha)",
                chart_type="bar",
                x_axis="tree_cover_gain_period",
                y_axis="area_ha",
                chart_data=rows,
            )
        ]
