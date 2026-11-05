"""Integrated deforestation alerts chart generator."""

from datetime import date, timedelta
from typing import List, Optional

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts.base import ChartGenerator

LOW_SERIES = "charts.label.low_confidence"
HIGH_SERIES = "charts.label.high_confidence"
HIGHEST_SERIES = "charts.label.highest_confidence"
# The series of each ``alert_confidence`` tier, from the bottom of a day's
# bar up.
TIER_SERIES = {
    "highest": HIGHEST_SERIES,
    "high": HIGH_SERIES,
    "low": LOW_SERIES,
}
# The tiers' colours on the map legend (project-zeno-next
# app/constants/datasets.ts), so a bar reads like the pixels it counts.
SERIES_COLORS = {
    HIGHEST_SERIES: "#C92A6D",
    HIGH_SERIES: "#DC6699",
    LOW_SERIES: "#EDA4C2",
}


def _days(start: date, end: date) -> list[str]:
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]


class IntegratedAlertsChartGenerator(ChartGenerator):
    """Integrated alerts: disturbed area per day as a stacked bar, one
    segment per ``alert_confidence`` tier (highest, high, low from the
    bottom up) — there are no driver or land-cover intersections to break
    down by.

    The most certain tier sits on the axis, so it compares day to day, and
    the high and highest total that the section's summary counts reads as
    the top of the middle segment. The order of the ticket's mock.

    Bars, not lines: most days in a two to four week window have no alerts,
    and a line interpolates across them, suggesting a continuous signal
    that is not there. The tiers are parts of one day's disturbed area, not
    competing trends.

    Daily, not monthly, because that is the resolution the data arrives at
    and the resolution the dataset is for: these alerts update whenever any
    source system does, and they are read over days and weeks.

    Rows are summed per (day, tier), since the analytics API returns one
    row per intersecting geometry and several can share a day. A tier with
    no alerts on a day with others is 0. With a period (``for_period``),
    every day of it gets a row, so the axis spans the whole period; a day
    with no alerts has only its date — a gap, not a zero: the API reports
    what it detected, and a fabricated zero is a claim about a day nobody
    looked at that way.
    """

    dataset_id = INTEGRATED_ALERTS_ID
    label_series = True

    def __init__(self, period: Optional[tuple[date, date]] = None):
        self._period = period

    def for_period(
        self, start: str, end: str
    ) -> "IntegratedAlertsChartGenerator":
        return IntegratedAlertsChartGenerator(
            (date.fromisoformat(start[:10]), date.fromisoformat(end[:10]))
        )

    def generate(self, rows: List[dict]) -> List[InsightChart]:
        totals: dict[str, dict[str, float]] = {}
        for row in rows:
            day = str(row.get("alert_date", ""))[:10]
            confidence = row.get("alert_confidence")
            if confidence not in TIER_SERIES:
                raise ValueError(f"Unknown alert confidence: {confidence!r}")
            tiers = totals.setdefault(day, dict.fromkeys(SERIES_COLORS, 0.0))
            tiers[TIER_SERIES[confidence]] += row.get("area_ha") or 0

        days = set(totals)
        if self._period is not None:
            days.update(_days(*self._period))
        return [
            InsightChart(
                position=0,
                title="charts.integrated_alerts.by_confidence",
                chart_type="stacked-bar",
                x_axis="alert_date",
                # Only the axis title: the series fields name the bars.
                y_axis="area_ha",
                series_fields=list(SERIES_COLORS),
                color_map=dict(SERIES_COLORS),
                chart_data=[
                    {"alert_date": day, **totals.get(day, {})}
                    for day in sorted(days)
                ],
            )
        ]
