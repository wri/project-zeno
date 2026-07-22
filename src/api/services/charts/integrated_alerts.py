from typing import List

from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator, monthly_totals

# Ascending confidence; "highest" means detected by two or more alert
# systems and may be absent when only one system covered the area/time.
CONFIDENCE_ORDER = ("low", "high", "highest")


class IntegratedAlertsChartGenerator(ChartGenerator):
    """Integrated alerts: monthly disturbed area over time, by confidence.

    Aggregates the daily ``area_ha`` rows into one line per
    ``alert_confidence`` tier. The data is pivoted wide (one column per
    tier, listed in ``series_fields``) because the frontend widget renders
    multi-series charts from ``series_fields`` and drops ``color_field``.
    """

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        data = monthly_totals(
            rows, "alert_date", "area_ha", group_column="alert_confidence"
        )
        if not data:
            # No rows means no series columns, which would fail the
            # InsightChart axis validation.
            return []
        tiers = {key for row in data for key in row if key != "month"}
        # Known tiers in ascending order; unexpected values are appended
        # rather than dropped so new upstream tiers stay visible.
        series = [tier for tier in CONFIDENCE_ORDER if tier in tiers]
        series += sorted(tiers - set(CONFIDENCE_ORDER))
        return [
            InsightChart(
                position=0,
                title="Integrated Deforestation Alerts by Confidence (ha)",
                chart_type="line",
                x_axis="month",
                series_fields=series,
                chart_data=data,
            )
        ]
