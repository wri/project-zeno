"""Global land cover chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import LAND_COVER_CHANGE_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator, by_area_desc


class LandCoverChangeChartGenerator(ChartGenerator):
    """Land cover composition as a pie, or class-to-class transitions as a
    table. Classes with no area are left out."""

    dataset_id = LAND_COVER_CHANGE_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        changed = by_area_desc(rows)
        if not changed:
            return []

        if "land_cover_class_end" in changed[0]:
            return [
                InsightChart(
                    position=0,
                    title="charts.land_cover.transitions",
                    chart_type="table",
                    chart_data=changed,
                )
            ]

        return [
            InsightChart(
                position=0,
                title="charts.land_cover.composition",
                chart_type="pie",
                x_axis="land_cover_class",
                y_axis="area_ha",
                chart_data=changed,
            )
        ]
