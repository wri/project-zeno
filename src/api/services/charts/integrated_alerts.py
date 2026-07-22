from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class IntegratedAlertsChartGenerator(ChartGenerator):
    """Integrated alerts: monthly disturbed area over time, by confidence.

    Aggregates the daily ``area_ha`` rows into a monthly line per
    ``alert_confidence`` (low / high / highest) — there are no driver or
    land-cover intersections to break down by.
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        totals: dict[tuple[str, str], float] = {}
        for row in rows:
            month = str(row.get("alert_date", ""))[:7]
            confidence = row.get("alert_confidence", "")
            totals[(month, confidence)] = totals.get(
                (month, confidence), 0
            ) + (row.get("area_ha") or 0)

        data = [
            {"month": month, "alert_confidence": confidence, "area_ha": area}
            for (month, confidence), area in sorted(totals.items())
        ]
        return [
            InsightChart(
                position=0,
                title="Integrated Deforestation Alerts by Confidence",
                chart_type="line",
                x_axis="month",
                y_axis="area_ha",
                color_field="alert_confidence",
                chart_data=data,
            )
        ]
