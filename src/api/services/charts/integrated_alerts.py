"""Integrated deforestation alerts chart generator."""

from typing import List

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator


class IntegratedAlertsChartGenerator(ChartGenerator):
    """Integrated alerts: daily disturbed area over time, by confidence.

    One point per day per ``alert_confidence`` (low / high / highest) — there
    are no driver or land-cover intersections to break down by.

    Daily, not monthly, because that is the resolution the data arrives at
    and the resolution the dataset is for: these alerts update whenever any
    source system does, and they are read over days and weeks. A monthly
    bucket also collapses the default two-week window to one or two points,
    which is not a line.

    Rows are summed per (day, confidence) rather than passed through, since
    the analytics API returns one row per intersecting geometry and several
    can share a day. Days with no alerts are absent rather than zero — the
    API reports what it detected, and a fabricated zero is a claim about a
    day nobody looked at that way.
    """

    dataset_id = INTEGRATED_ALERTS_ID

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        totals: dict[tuple[str, str], float] = {}
        for row in rows:
            day = str(row.get("alert_date", ""))[:10]
            confidence = row.get("alert_confidence", "")
            totals[(day, confidence)] = totals.get((day, confidence), 0) + (
                row.get("area_ha") or 0
            )

        data = [
            {
                "alert_date": day,
                "alert_confidence": confidence,
                "area_ha": area,
            }
            for (day, confidence), area in sorted(totals.items())
        ]
        return [
            InsightChart(
                position=0,
                title="charts.integrated_alerts.by_confidence",
                chart_type="line",
                x_axis="alert_date",
                y_axis="area_ha",
                color_field="alert_confidence",
                chart_data=data,
            )
        ]
