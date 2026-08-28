"""Global land cover chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import LAND_COVER_CHANGE_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class LandCoverChangeChartGenerator(ChartGenerator):
    """Land cover composition as a pie, or class-to-class transitions as a
    table. Classes with no area are left out."""

    def __init__(self, dataset_id: int = LAND_COVER_CHANGE_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        changed = sorted(
            (row for row in rows if (row.get("area_ha") or 0) > 0),
            key=lambda row: row["area_ha"],
            reverse=True,
        )
        if not changed:
            return []

        if "land_cover_class_end" in changed[0]:
            return [
                InsightChart(
                    position=0,
                    title="Land Cover Transitions, 2015 to 2024",
                    chart_type="table",
                    chart_data=changed,
                )
            ]

        return [
            InsightChart(
                position=0,
                title="Land Cover Composition in 2024",
                chart_type="pie",
                x_axis="land_cover_class",
                y_axis="area_ha",
                chart_data=changed,
            )
        ]
