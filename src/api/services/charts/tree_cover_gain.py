"""Tree cover gain chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_GAIN_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class TreeCoverGainChartGenerator(ChartGenerator):
    """Tree cover gain: one bar per reporting period.

    The catalog describes cumulative periods (2000-2020, 2005-2020, ...) but
    the API returns whatever periods it returns — discrete 5-year intervals
    in practice. Either way the raw `tree_cover_gain_period` label is used
    verbatim and never decomposed or re-derived, so the bars always mean
    exactly what the API said.
    """

    def __init__(self, dataset_id: int = TREE_COVER_GAIN_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = sorted(
            (row for row in rows if (row.get("area_ha") or 0) > 0),
            key=lambda row: row.get("tree_cover_gain_period") or "",
        )
        if not present:
            return []
        return [
            InsightChart(
                position=0,
                title="Tree Cover Gain by Period",
                chart_type="bar",
                x_axis="tree_cover_gain_period",
                y_axis="area_ha",
                chart_data=present,
            )
        ]
