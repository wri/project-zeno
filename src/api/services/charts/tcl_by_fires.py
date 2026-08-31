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

    def __init__(self, dataset_id: int = TREE_COVER_LOSS_BY_FIRES_ID):
        self.dataset_id = dataset_id

    def can_handle(self, dataset_id: int) -> bool:
        return dataset_id == self.dataset_id

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
                    title="Tree Cover Loss from Fires vs Other Causes",
                    chart_type="pie",
                    x_axis="cause",
                    y_axis="area_ha",
                    chart_data=[
                        {
                            "cause": "Fires",
                            "area_ha": row.get(FIRE_SERIES[0]) or 0,
                        },
                        {
                            "cause": "Other",
                            "area_ha": row.get(FIRE_SERIES[1]) or 0,
                        },
                    ],
                )
            ]

        return [
            InsightChart(
                position=0,
                title="Annual Tree Cover Loss from Fires vs Other Causes",
                chart_type="stacked-bar",
                x_axis="tree_cover_loss_year",
                series_fields=FIRE_SERIES,
                chart_data=present,
            )
        ]
