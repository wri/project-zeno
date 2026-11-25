"""High and highest confidence integrated alerts area in each dashboard's
AOI over a period, by default the week ending on the latest alert date. If
that date is unavailable, the default is the latest full Sunday-to-Saturday
week."""

import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Iterable, Optional, Protocol
from uuid import UUID

import cachetools
import httpx
import pandas as pd

from src.agent.datasets.handlers.analytics_handler import (
    ADMIN_SUBTYPES,
    ANALYTICS_ADMIN_SUBTYPES,
    INTEGRATED_ALERTS_ID,
    analytics_api_headers,
)
from src.agent.datasets.handlers.base import DataSourceHandler
from src.shared.geocoding_helpers import format_id
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

SATURDAY = 5
# The default period: the latest alert date and the days before it.
DEFAULT_PERIOD_DAYS = 7
LATEST_ALERT_DATE_PATH = "/v0/land_change/integrated_alerts/latest"
LATEST_ALERT_DATE_TIMEOUT_SECONDS = 10.0
# At most this many single-area pulls (custom areas and GADM levels 3 to 5)
# at once, so one dashboards page cannot flood the analytics API.
SINGLE_AREA_CONCURRENCY = 8
# The longest wait for single-area pulls: enough for a result the analytics
# API already holds (its saved-area check takes up to about 6 s); slower areas
# are unavailable this time and come from its cache on the next load.
SINGLE_AREA_TIMEOUT_SECONDS = 10.0

# The latest alert date changes at most daily, so keep it for an hour.
_latest_alert_date_cache: cachetools.TTLCache = cachetools.TTLCache(
    maxsize=4, ttl=60 * 60
)


class AlertsUnavailableError(Exception):
    pass


class UnexpectedAlertsDataError(AlertsUnavailableError):
    """The analytics API answered with rows this module cannot read."""


class InvalidPeriodError(ValueError):
    pass


# The confidence tiers counted, each as a column in the alerts list. Low
# confidence alerts are left out: they are single detections by one system.
LISTED_CONFIDENCES = ("high", "highest")
EXCLUDED_CONFIDENCES = ("low",)
# The columns the summary reads from the analytics result.
SUMMARY_COLUMNS = ("aoi_id", "alert_confidence", "area_ha")


def read_alert_rows(
    data: Optional[dict], names: tuple[str, ...]
) -> pd.DataFrame:
    """Read the named columns of an analytics result, a missing area
    counting as 0 as on the alerts chart. Raises
    ``UnexpectedAlertsDataError`` for a result it cannot read, including an
    unknown confidence tier, so that a new tier is never counted or dropped
    unseen."""
    if not data or not any(data.values()):
        return pd.DataFrame(columns=list(names))
    if missing := [name for name in names if name not in data]:
        raise UnexpectedAlertsDataError(
            f"The integrated alerts result has no {', '.join(missing)} column."
        )
    if len({len(data[name]) for name in names}) > 1:
        raise UnexpectedAlertsDataError(
            "The integrated alerts result has columns of different lengths."
        )
    alerts = pd.DataFrame({name: data[name] for name in names})
    try:
        alerts["area_ha"] = pd.to_numeric(alerts["area_ha"]).fillna(0.0)
    except (TypeError, ValueError) as error:
        raise UnexpectedAlertsDataError(
            f"Unexpected alert area: {error}"
        ) from error
    known = {*LISTED_CONFIDENCES, *EXCLUDED_CONFIDENCES}
    if unknown := set(alerts["alert_confidence"]) - known:
        raise UnexpectedAlertsDataError(f"Unknown alert confidence: {unknown}")
    return alerts


@dataclass(frozen=True)
class DashboardAlerts:
    integrated_alerts: Optional[float]
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertsReport:
    start_date: date
    end_date: date
    dashboards: dict[UUID, DashboardAlerts]


class AlertsSource(Protocol):
    async def area_ha_by_src_id(
        self, aois: list[dict], start: date, end: date
    ) -> dict[str, float]:
        """Alert area of each AOI that has alerts."""
        ...

    async def latest_alert_date(self) -> date:
        """The latest date with any alert."""
        ...


def latest_alert_week(today: date) -> tuple[date, date]:
    """The last Sunday-to-Saturday week that ended before today."""
    days_since_saturday = (today.weekday() - SATURDAY) % 7 or 7
    end = today - timedelta(days=days_since_saturday)
    return end - timedelta(days=6), end


def period_ending(end: date) -> tuple[date, date]:
    return end - timedelta(days=DEFAULT_PERIOD_DAYS - 1), end


def is_custom_area(aoi: dict) -> bool:
    return aoi["subtype"] == "custom-area"


def supports_alerts(aoi: dict) -> bool:
    return is_custom_area(aoi) or (
        aoi["source"] == "gadm" and aoi["subtype"] in ADMIN_SUBTYPES
    )


def has_precomputed_alerts(aoi: dict) -> bool:
    """Whether the analytics API reads the area's alerts from precomputed
    results, which it serves for many areas in one request."""
    return (
        aoi["source"] == "gadm" and aoi["subtype"] in ANALYTICS_ADMIN_SUBTYPES
    )


def distinct_aois(aois: Iterable[dict]) -> list[dict]:
    return list({aoi["src_id"]: aoi for aoi in aois}.values())


def unavailable() -> DashboardAlerts:
    return DashboardAlerts(
        integrated_alerts=None,
        errors={"integrated_alerts": "Integrated alerts data is unavailable"},
    )


class DashboardAlertsService:
    def __init__(
        self,
        source: AlertsSource,
        today: Callable[[], date] = date.today,
        single_area_timeout_seconds: float = SINGLE_AREA_TIMEOUT_SECONDS,
    ):
        self.source = source
        self.today = today
        self.single_area_timeout_seconds = single_area_timeout_seconds

    async def summarize(
        self,
        aoi_by_dashboard: dict[UUID, Optional[dict]],
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> AlertsReport:
        """High and highest confidence alerts between start and end, which
        default together to the week ending on the latest alert date. A
        dashboard whose alerts cannot be fetched or read is unavailable."""
        if (start is None) != (end is None):
            raise InvalidPeriodError(
                "Send both start_date and end_date, or neither."
            )
        if start is None or end is None:
            start, end = await self._default_period()
        if start > end:
            raise InvalidPeriodError(f"{start} is after {end}.")
        supported = {
            dashboard_id: aoi
            for dashboard_id, aoi in aoi_by_dashboard.items()
            if aoi is not None and supports_alerts(aoi)
        }
        alerts_by_src_id = await self._alerts_by_src_id(
            distinct_aois(supported.values()), start, end
        )
        return AlertsReport(
            start_date=start,
            end_date=end,
            dashboards={
                dashboard_id: alerts_by_src_id[aoi["src_id"]]
                for dashboard_id, aoi in supported.items()
            },
        )

    async def _default_period(self) -> tuple[date, date]:
        try:
            return period_ending(await self.source.latest_alert_date())
        except AlertsUnavailableError as error:
            logger.warning(
                "dashboard_alerts_latest_date_unavailable", error=str(error)
            )
            return latest_alert_week(self.today())

    async def _alerts_by_src_id(
        self, aois: list[dict], start: date, end: date
    ) -> dict[str, DashboardAlerts]:
        """Precomputed areas in one request, every other area in its own.

        The analytics API refuses a whole request for one unsaved custom
        area, and computes custom areas and GADM levels 3 to 5 on the fly,
        never mixed with precomputed levels. So one unsaved, deleted or slow
        area must not fail or hold up the others.
        """
        precomputed_alerts, computed_alerts = await asyncio.gather(
            self._pull(
                [aoi for aoi in aois if has_precomputed_alerts(aoi)],
                start,
                end,
            ),
            self._pull_each(
                [aoi for aoi in aois if not has_precomputed_alerts(aoi)],
                start,
                end,
            ),
        )
        return {**precomputed_alerts, **computed_alerts}

    async def _pull_each(
        self, aois: list[dict], start: date, end: date
    ) -> dict[str, DashboardAlerts]:
        """Each AOI's alerts from its own request, at most
        SINGLE_AREA_CONCURRENCY at once. An AOI whose request is not done
        within single_area_timeout_seconds of the start is unavailable."""
        if not aois:
            return {}
        slots = asyncio.Semaphore(SINGLE_AREA_CONCURRENCY)

        async def pull_one(aoi: dict) -> dict[str, DashboardAlerts]:
            async with slots:
                return await self._pull([aoi], start, end)

        tasks = {
            aoi["src_id"]: asyncio.create_task(pull_one(aoi)) for aoi in aois
        }
        _, pending = await asyncio.wait(
            tasks.values(), timeout=self.single_area_timeout_seconds
        )
        for task in pending:
            task.cancel()
        # Let the cancelled requests unwind before their tasks are dropped.
        await asyncio.gather(*pending, return_exceptions=True)
        late = [src_id for src_id, task in tasks.items() if task in pending]
        if late:
            # Ids only: custom area names are user text.
            logger.warning(
                "dashboard_alerts_single_area_timeout",
                src_ids=late,
                timeout_seconds=self.single_area_timeout_seconds,
            )
        alerts = {src_id: unavailable() for src_id in late}
        for src_id, task in tasks.items():
            if task not in pending:
                alerts.update(task.result())
        return alerts

    async def _pull(
        self, aois: list[dict], start: date, end: date
    ) -> dict[str, DashboardAlerts]:
        """The AOIs' alerts from one request; all unavailable if it fails."""
        if not aois:
            return {}
        try:
            area_ha = await self.source.area_ha_by_src_id(aois, start, end)
        except AlertsUnavailableError as error:
            logger.warning("dashboard_alerts_unavailable", error=str(error))
            return {aoi["src_id"]: unavailable() for aoi in aois}
        return {
            aoi["src_id"]: DashboardAlerts(
                integrated_alerts=area_ha.get(aoi["src_id"], 0.0)
            )
            for aoi in aois
        }


def total_area_ha_by_aoi_id(data: Optional[dict]) -> dict[str, float]:
    """High and highest confidence alert area of each AOI that has such
    alerts, by the alerts list's rules. Raises ``UnexpectedAlertsDataError``
    for a result it cannot read."""
    alerts = read_alert_rows(data, SUMMARY_COLUMNS)
    listed = alerts[alerts["alert_confidence"].isin(LISTED_CONFIDENCES)]
    return listed.groupby("aoi_id")["area_ha"].sum().to_dict()


class AnalyticsAlertsSource:
    def __init__(
        self,
        handler: DataSourceHandler,
        base_url: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.handler = handler
        self.base_url = base_url
        self.transport = transport

    async def latest_alert_date(self) -> date:
        url = self.base_url + LATEST_ALERT_DATE_PATH
        if (cached := _latest_alert_date_cache.get(url)) is not None:
            return cached
        try:
            async with httpx.AsyncClient(
                timeout=LATEST_ALERT_DATE_TIMEOUT_SECONDS,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    url, headers=analytics_api_headers()
                )
                response.raise_for_status()
            alert_date = date.fromisoformat(
                response.json()["data"]["alert_date"]
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise AlertsUnavailableError(
                f"No latest alert date: {error!r}"
            ) from error
        _latest_alert_date_cache[url] = alert_date
        return alert_date

    async def area_ha_by_src_id(
        self, aois: list[dict], start: date, end: date
    ) -> dict[str, float]:
        result = await self.handler.pull_data(
            query="",
            dataset={"dataset_id": INTEGRATED_ALERTS_ID},
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            change_over_time_query=False,
            aois=[dict(aoi) for aoi in aois],
        )
        if not result.success:
            raise AlertsUnavailableError(result.message)
        src_id_by_aoi_id = {
            format_id(aoi["src_id"]): aoi["src_id"] for aoi in aois
        }
        return {
            src_id_by_aoi_id[aoi_id]: area_ha
            for aoi_id, area_ha in total_area_ha_by_aoi_id(
                result.data or {}
            ).items()
        }
