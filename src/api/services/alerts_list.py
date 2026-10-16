"""Integrated alerts in one area, one row per alert day.

The live alerts list on a dashboard (``POST /api/alerts/list``) and the
``nrt-monitoring`` template both read this. Nothing is written to the
database: each call is one analytics pull, which the analytics API caches by
payload.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from src.api.services.dashboard_alerts import AlertsUnavailableError

# The confidence tiers the list shows, each as a column. Low confidence
# alerts are left out: they are single detections by one system.
LISTED_CONFIDENCES = ("high", "highest")
EXCLUDED_CONFIDENCES = ("low",)
# The only columns read from the analytics result. The handler also adds the
# AOI name, and the API the AOI id and type; one pull is one AOI, so they
# carry nothing.
ALERT_COLUMNS = ("alert_date", "alert_confidence", "area_ha")


class UnexpectedAlertsDataError(AlertsUnavailableError):
    """The analytics API answered with rows this module cannot read."""


@dataclass(frozen=True)
class AlertDay:
    alert_date: date
    high_ha: float
    highest_ha: float
    total_ha: float
    # The day is in the latest full alert week.
    new: bool


def _parse_date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise UnexpectedAlertsDataError(
            f"Unexpected alert date: {value!r}"
        ) from error


def _area(value: Any) -> float:
    """Hectares; a missing area counts as 0, as on the alerts chart."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise UnexpectedAlertsDataError(
            f"Unexpected alert area: {value!r}"
        ) from error


def _columns(data: Optional[dict]) -> list[list]:
    """The three alert columns, or empty lists for an empty result."""
    if not data or not any(data.values()):
        return [[] for _ in ALERT_COLUMNS]
    missing = [column for column in ALERT_COLUMNS if column not in data]
    if missing:
        raise UnexpectedAlertsDataError(
            f"The integrated alerts result has no {', '.join(missing)} "
            "column."
        )
    columns = [list(data[column]) for column in ALERT_COLUMNS]
    if len({len(column) for column in columns}) > 1:
        raise UnexpectedAlertsDataError(
            "The integrated alerts result has columns of different lengths."
        )
    return columns


def alert_days(
    data: Optional[dict], new_week: tuple[date, date]
) -> list[AlertDay]:
    """One row per day with high or highest confidence alerts, newest first.

    ``data`` is the column-oriented analytics result; it is not changed.
    Rows that repeat a day and a tier (one per intersecting geometry) are
    summed. A tier with no alerts on a day is 0. A day with no high or
    highest confidence area has no row: nothing is made up for a day the
    data does not report. Raises ``UnexpectedAlertsDataError`` for a result
    it cannot read, such as an unknown confidence tier.
    """
    areas: dict[date, dict[str, list[float]]] = defaultdict(
        lambda: {confidence: [] for confidence in LISTED_CONFIDENCES}
    )
    for raw_date, confidence, area in zip(*_columns(data)):
        if confidence in EXCLUDED_CONFIDENCES:
            continue
        if confidence not in LISTED_CONFIDENCES:
            raise UnexpectedAlertsDataError(
                f"Unknown alert confidence: {confidence!r}"
            )
        areas[_parse_date(raw_date)][confidence].append(_area(area))

    days = []
    for day in sorted(areas, reverse=True):
        high_ha = math.fsum(areas[day]["high"])
        highest_ha = math.fsum(areas[day]["highest"])
        if high_ha + highest_ha == 0:
            continue
        days.append(
            AlertDay(
                alert_date=day,
                high_ha=high_ha,
                highest_ha=highest_ha,
                total_ha=high_ha + highest_ha,
                new=new_week[0] <= day <= new_week[1],
            )
        )
    return days
