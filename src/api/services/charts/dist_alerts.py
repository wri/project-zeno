from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator, monthly_totals


class DistAlertsChartGenerator(ChartGenerator):
    """DIST-ALERT: monthly disturbed area over time as a single line.

    The analyze path sends no intersections, so there is no driver or
    land-cover breakdown to plot; daily rows are summed per calendar month
    across confidence levels.
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        data = monthly_totals(rows, "dist_alert_date", "area_ha")
        return [
            InsightChart(
                position=0,
                title="Ecosystem Disturbance Alerts Over Time (ha)",
                chart_type="line",
                x_axis="month",
                y_axis="area_ha",
                chart_data=data,
            )
        ]
