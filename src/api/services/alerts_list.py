"""Integrated alerts in one area, one row per alert day.

The live alerts list on a dashboard (``POST /api/alerts/list``) and the
``nrt-monitoring`` template both read this. Nothing is written to the
database: each call is one analytics pull, which the analytics API caches by
payload.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional, get_args

from src.agent.datasets.dates import revise_date_range
from src.agent.datasets.handlers.analytics_handler import (
    ANALYTICS_AOI_SUBTYPES,
    INTEGRATED_ALERTS_ID,
)
from src.agent.datasets.handlers.base import DataSourceHandler
from src.api.schemas import ALERTS_MAX_DAYS, AlertsLandFilter
from src.api.services.dashboard_alerts import (
    AlertsUnavailableError,
    latest_alert_week,
)

# The confidence tiers the list shows, each as a column. Low confidence
# alerts are left out: they are single detections by one system.
LISTED_CONFIDENCES = ("high", "highest")
EXCLUDED_CONFIDENCES = ("low",)
# The only columns read from the analytics result. The handler also adds the
# AOI name, and the API the AOI id and type; one pull is one AOI, so they
# carry nothing.
ALERT_COLUMNS = ("alert_date", "alert_confidence", "area_ha")
# The period when the caller gives no start date, counted back from the end.
ALERTS_LIST_DEFAULT_DAYS = 30
# The land classes the list can be restricted to. The handler sends each,
# given as the dataset's context layer, as the analytics API's land_filter.
ALERTS_LAND_FILTERS: tuple[str, ...] = get_args(AlertsLandFilter)


class UnexpectedAlertsDataError(AlertsUnavailableError):
    """The analytics API answered with rows this module cannot read."""


class UnsupportedAreaError(ValueError):
    """The analytics API takes no integrated alerts request for this area."""


class InvalidWindowError(ValueError):
    """The requested period is empty or too long."""


@dataclass(frozen=True)
class AlertDay:
    alert_date: date
    high_ha: float
    highest_ha: float
    # The day is in the latest full alert week.
    new: bool

    @property
    def total_ha(self) -> float:
        return self.high_ha + self.highest_ha


@dataclass(frozen=True)
class AlertsWeek:
    start_date: date
    end_date: date


@dataclass(frozen=True)
class AlertsList:
    # The latest alert date in the pulled data, any confidence; None when
    # the pull returned no rows. Shown as "DATA TO", and the frontend counts
    # its periods back from it.
    data_to: Optional[date]
    # The period pulled, clamped to the data and to today.
    start_date: date
    end_date: date
    new_week: AlertsWeek
    rows: list[AlertDay]

    @property
    def total_area_ha(self) -> float:
        return math.fsum(row.total_ha for row in self.rows)


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


def latest_alert_date(data: Optional[dict]) -> Optional[date]:
    """The most recent alert date in the result, of any confidence tier: a
    low confidence alert is data arriving too. None for an empty result."""
    dates, _, _ = _columns(data)
    return max((_parse_date(value) for value in dates), default=None)


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
                new=new_week[0] <= day <= new_week[1],
            )
        )
    return days


class AlertsListService:
    """One area's alert days over a period, from one analytics pull."""

    def __init__(self, handler: DataSourceHandler):
        self.handler = handler

    async def window(
        self, start: Optional[date], end: Optional[date], today: date
    ) -> tuple[date, date]:
        """The period to pull. The end defaults to today and is capped at
        today; the start defaults to 30 days before the end. Both are then
        clamped to the integrated alerts data. Raises ``InvalidWindowError``
        for an empty period or one longer than 365 days."""
        end = min(end or today, today)
        start = start or end - timedelta(days=ALERTS_LIST_DEFAULT_DAYS)
        clamped_start, clamped_end, _ = await revise_date_range(
            start.isoformat(), end.isoformat(), INTEGRATED_ALERTS_ID
        )
        start = date.fromisoformat(clamped_start)
        end = date.fromisoformat(clamped_end)
        if start > end:
            raise InvalidWindowError(
                f"The start date {start} is after the end date {end}, once "
                "both are limited to the dates the integrated alerts data "
                "covers (up to today)."
            )
        if (end - start).days > ALERTS_MAX_DAYS:
            raise InvalidWindowError(
                f"The period from {start} to {end} is longer than "
                f"{ALERTS_MAX_DAYS} days."
            )
        return start, end

    async def list(
        self,
        aoi: dict,
        start: Optional[date] = None,
        end: Optional[date] = None,
        *,
        today: date,
        land_filter: Optional[str] = None,
    ) -> AlertsList:
        """The alert days in ``aoi`` (``source``, ``src_id``, ``subtype``).

        ``today`` sets the default period, caps its end and picks the
        latest alert week, so one request uses one date throughout.
        ``land_filter`` restricts the alerts to one land class; None is all
        land. Raises ``UnsupportedAreaError`` or ``InvalidWindowError``
        before any pull, and ``AlertsUnavailableError`` when the pull fails
        or its result cannot be read.
        """
        # The handler sends no filter for a context layer it does not know,
        # which would silently list alerts on all land.
        if land_filter is not None and land_filter not in ALERTS_LAND_FILTERS:
            raise ValueError(f"Unknown land filter: {land_filter!r}")
        if aoi.get("subtype") not in ANALYTICS_AOI_SUBTYPES:
            raise UnsupportedAreaError(
                f"The integrated alerts list is not available for "
                f"{aoi.get('subtype')!r} areas. It is available for "
                "countries, states or provinces, districts or counties, "
                "protected areas, key biodiversity areas, indigenous lands, "
                "custom areas and concessions."
            )
        start, end = await self.window(start, end, today)
        # Without a land filter the dataset is exactly what AnalyzeService
        # sends, so a template build makes one pull for its chart and list.
        dataset: dict[str, Any] = {"dataset_id": INTEGRATED_ALERTS_ID}
        if land_filter is not None:
            dataset["context_layer"] = land_filter
        # A copy: the handler strips the GADM suffix of its input in place.
        result = await self.handler.pull_data(
            query="",
            dataset=dataset,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            change_over_time_query=False,
            aois=[dict(aoi)],
        )
        if not result.success:
            raise AlertsUnavailableError(result.message)
        week = latest_alert_week(today)
        return AlertsList(
            data_to=latest_alert_date(result.data),
            start_date=start,
            end_date=end,
            new_week=AlertsWeek(*week),
            rows=alert_days(result.data, week),
        )
