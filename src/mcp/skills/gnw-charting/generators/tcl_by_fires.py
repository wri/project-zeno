"""Tree cover loss from fires chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_BY_FIRES_ID,
)
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

FIRE_SERIES = [
    "tree_cover_loss_from_fires_area_ha",
    "tree_cover_loss_non_fires_area_ha",
]


class TCLByFiresChartGenerator(ChartGenerator):
    """Fire versus non-fire tree cover loss per year as a stacked bar, or a
    pie of the two when only one year is in range."""

    dataset_id = TREE_COVER_LOSS_BY_FIRES_ID
    label_fields = ("cause",)

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        present = sorted(
            (
                row
                for row in rows
                if any((row.get(field) or 0) > 0 for field in FIRE_SERIES)
            ),
            key=lambda row: row.get("tree_cover_loss_year") or 0,
        )
        if not present:
            return []

        if len(present) == 1:
            row = present[0]
            return [
                InsightChart(
                    position=0,
                    title="charts.tcl_by_fires.split",
                    chart_type="pie",
                    x_axis="cause",
                    y_axis="area_ha",
                    chart_data=[
                        {
                            "cause": "charts.label.fires",
                            "area_ha": row.get(FIRE_SERIES[0]) or 0,
                        },
                        {
                            "cause": "charts.label.other",
                            "area_ha": row.get(FIRE_SERIES[1]) or 0,
                        },
                    ],
                )
            ]

        return [
            InsightChart(
                position=0,
                title="charts.tcl_by_fires.annual_split",
                chart_type="stacked-bar",
                x_axis="tree_cover_loss_year",
                series_fields=FIRE_SERIES,
                chart_data=present,
            )
        ]
