import copy
from datetime import date

import pytest

from src.agent.datasets.handlers.analytics_handler import INTEGRATED_ALERTS_ID
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.api.services.alerts_list import (
    AlertDay,
    AlertsListService,
    AlertsUnavailableError,
    AlertsWeek,
    InvalidWindowError,
    UnexpectedAlertsDataError,
    UnsupportedAreaError,
    alert_days,
)

WEEK = (date(2026, 10, 4), date(2026, 10, 10))
# A Friday; the latest full alert week is WEEK.
TODAY = date(2026, 10, 16)
PARANA = {
    "source": "gadm",
    "src_id": "BRA.16_1",
    "subtype": "state-province",
}


def _rows(*rows):
    """Column-oriented analytics data from (date, confidence, area) rows."""
    return {
        "alert_date": [row[0] for row in rows],
        "alert_confidence": [row[1] for row in rows],
        "area_ha": [row[2] for row in rows],
    }


def test_one_row_per_day_newest_first_with_tiers_as_columns():
    data = _rows(
        ("2026-10-02", "high", 1.5),
        ("2026-10-09", "high", 12.5),
        ("2026-10-09", "highest", 3.0),
    )

    assert alert_days(data, WEEK) == [
        AlertDay(date(2026, 10, 9), 12.5, 3.0, 15.5, new=True),
        AlertDay(date(2026, 10, 2), 1.5, 0.0, 1.5, new=False),
    ]


def test_a_tier_with_no_alerts_on_a_day_is_zero():
    (day,) = alert_days(_rows(("2026-10-09", "highest", 2.0)), WEEK)

    assert (day.high_ha, day.highest_ha, day.total_ha) == (0.0, 2.0, 2.0)


def test_rows_that_repeat_a_day_and_tier_are_summed():
    data = _rows(
        ("2026-10-09", "high", 1.0),
        ("2026-10-09", "high", 2.5),
        ("2026-10-09", "highest", 0.5),
        ("2026-10-09", "highest", 0.25),
    )

    (day,) = alert_days(data, WEEK)

    assert (day.high_ha, day.highest_ha, day.total_ha) == (3.5, 0.75, 4.25)


def test_sums_do_not_drift():
    data = _rows(*[("2026-10-09", "high", 0.1)] * 10)

    (day,) = alert_days(data, WEEK)

    assert day.high_ha == 1.0


def test_low_confidence_is_left_out():
    data = _rows(
        ("2026-10-09", "low", 40.0),
        ("2026-10-09", "high", 2.0),
        ("2026-10-08", "low", 5.0),
    )

    (day,) = alert_days(data, WEEK)

    assert day.alert_date == date(2026, 10, 9)
    assert day.total_ha == 2.0


def test_a_missing_area_counts_as_zero():
    data = _rows(
        ("2026-10-09", "high", None),
        ("2026-10-09", "high", 2.0),
        ("2026-10-08", "highest", None),
    )

    assert alert_days(data, WEEK) == [
        AlertDay(date(2026, 10, 9), 2.0, 0.0, 2.0, new=True)
    ]


@pytest.mark.parametrize(
    "day, new",
    [
        ("2026-10-03", False),
        ("2026-10-04", True),
        ("2026-10-10", True),
        ("2026-10-11", False),
    ],
)
def test_new_means_inside_the_latest_alert_week(day, new):
    (row,) = alert_days(_rows((day, "high", 1.0)), WEEK)

    assert row.new is new


def test_other_columns_are_ignored():
    data = {
        **_rows(("2026-10-09T00:00:00", "high", 1.0)),
        "aoi_id": ["BRA.16"],
        "aoi_type": ["admin"],
        "name": ["Paraná"],
    }

    (day,) = alert_days(data, WEEK)

    assert day.alert_date == date(2026, 10, 9)


def test_the_result_is_not_changed():
    data = _rows(("2026-10-09", "high", 1.0), ("2026-10-09", "low", 2.0))
    before = copy.deepcopy(data)

    alert_days(data, WEEK)

    assert data == before


@pytest.mark.parametrize(
    "data",
    [None, {}, _rows(), {"aoi_id": [], "name": []}],
    ids=["none", "empty-dict", "empty-columns", "other-empty-columns"],
)
def test_an_empty_result_has_no_rows(data):
    assert alert_days(data, WEEK) == []


@pytest.mark.parametrize(
    "data, problem",
    [
        (_rows(("2026-10-09", "nominal", 1.0)), "Unknown alert confidence"),
        (
            {"alert_date": ["2026-10-09"], "area_ha": [1.0]},
            "no alert_confidence column",
        ),
        (
            {
                "alert_date": ["2026-10-09", "2026-10-08"],
                "alert_confidence": ["high"],
                "area_ha": [1.0],
            },
            "different lengths",
        ),
        (_rows(("yesterday", "high", 1.0)), "Unexpected alert date"),
        (_rows(("2026-10-09", "high", "a lot")), "Unexpected alert area"),
    ],
    ids=[
        "unknown-tier",
        "missing-column",
        "ragged-columns",
        "bad-date",
        "bad-area",
    ],
)
def test_a_result_it_cannot_read_raises(data, problem):
    with pytest.raises(UnexpectedAlertsDataError, match=problem):
        alert_days(data, WEEK)


class FakeHandler(DataSourceHandler):
    def __init__(self, result=None):
        self.result = result or DataPullResult(
            success=True, data={}, message=""
        )
        self.calls = []

    def can_handle(self, dataset) -> bool:
        return True

    async def pull_data(
        self,
        query,
        dataset,
        start_date,
        end_date,
        change_over_time_query,
        aois,
    ):
        self.calls.append(
            {
                "dataset": dataset,
                "start_date": start_date,
                "end_date": end_date,
                "change_over_time_query": change_over_time_query,
                "aois": [dict(aoi) for aoi in aois],
            }
        )
        # The analytics handler strips the GADM suffix in place.
        for aoi in aois:
            aoi["src_id"] = aoi["src_id"].removesuffix("_1")
        return self.result


async def _list(handler=None, aoi=PARANA, **kwargs):
    service = AlertsListService(handler or FakeHandler())
    return await service.list(dict(aoi), today=TODAY, **kwargs)


@pytest.mark.asyncio
async def test_defaults_to_the_30_days_to_today():
    handler = FakeHandler()

    alerts = await _list(handler)

    (call,) = handler.calls
    assert (call["start_date"], call["end_date"]) == (
        "2026-09-16",
        "2026-10-16",
    )
    assert (alerts.start_date, alerts.end_date) == (
        date(2026, 9, 16),
        TODAY,
    )
    assert alerts.data_to == TODAY
    assert alerts.new_week == AlertsWeek(*WEEK)


@pytest.mark.asyncio
async def test_pulls_integrated_alerts_once_for_a_copy_of_the_area():
    handler = FakeHandler()
    aoi = dict(PARANA)

    await AlertsListService(handler).list(aoi, today=TODAY)

    (call,) = handler.calls
    assert call["dataset"] == {"dataset_id": INTEGRATED_ALERTS_ID}
    assert call["change_over_time_query"] is False
    assert call["aois"] == [PARANA]
    assert aoi == PARANA


@pytest.mark.asyncio
@pytest.mark.parametrize("land_filter", ["natural_lands", "natural_forests"])
async def test_a_land_filter_restricts_the_pull_to_that_land(land_filter):
    data = _rows(
        ("2026-10-09", "high", 2.0),
        ("2026-10-09", "low", 7.0),
    )
    handler = FakeHandler(DataPullResult(success=True, data=data, message=""))

    alerts = await _list(handler, land_filter=land_filter)

    (call,) = handler.calls
    assert call["dataset"] == {
        "dataset_id": INTEGRATED_ALERTS_ID,
        "context_layer": land_filter,
    }
    # The rows of a filtered pull are pivoted like any other.
    assert alerts.rows == [
        AlertDay(date(2026, 10, 9), 2.0, 0.0, 2.0, new=True)
    ]
    assert alerts.total_area_ha == 2.0


@pytest.mark.asyncio
async def test_an_unknown_land_filter_never_reaches_the_api():
    handler = FakeHandler()

    with pytest.raises(ValueError, match="Unknown land filter"):
        await _list(handler, land_filter="intact_forest")

    assert handler.calls == []


@pytest.mark.asyncio
async def test_rows_and_total():
    data = _rows(
        ("2026-10-09", "high", 12.5),
        ("2026-10-09", "highest", 3.0),
        ("2026-09-20", "high", 0.1),
        ("2026-09-20", "low", 7.0),
    )
    handler = FakeHandler(DataPullResult(success=True, data=data, message=""))

    alerts = await _list(handler)

    assert alerts.rows == [
        AlertDay(date(2026, 10, 9), 12.5, 3.0, 15.5, new=True),
        AlertDay(date(2026, 9, 20), 0.1, 0.0, 0.1, new=False),
    ]
    assert alerts.total_area_ha == 15.6


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start, end, pulled",
    [
        (
            date(2026, 10, 1),
            date(2026, 12, 31),
            ("2026-10-01", "2026-10-16"),
        ),
        (
            date(2023, 1, 1),
            date(2023, 12, 31),
            ("2023-12-01", "2023-12-31"),
        ),
        (None, date(2026, 10, 1), ("2026-09-01", "2026-10-01")),
        (date(2025, 10, 16), None, ("2025-10-16", "2026-10-16")),
    ],
    ids=[
        "future-end-capped-at-today",
        "start-before-the-data",
        "start-defaults-to-30-days-before-the-end",
        "exactly-365-days",
    ],
)
async def test_the_period_is_clamped(start, end, pulled):
    handler = FakeHandler()

    alerts = await _list(handler, start=start, end=end)

    (call,) = handler.calls
    assert (call["start_date"], call["end_date"]) == pulled
    assert (alerts.start_date.isoformat(), alerts.end_date.isoformat()) == (
        pulled
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start, end",
    [
        (date(2026, 10, 10), date(2026, 10, 4)),
        (date(2026, 10, 20), None),
        (None, date(2023, 6, 1)),
        (date(2025, 10, 15), None),
    ],
    ids=[
        "start-after-end",
        "start-after-today",
        "end-before-the-data",
        "longer-than-365-days",
    ],
)
async def test_an_invalid_period_never_reaches_the_api(start, end):
    handler = FakeHandler()

    with pytest.raises(InvalidWindowError):
        await _list(handler, start=start, end=end)

    assert handler.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "aoi",
    [
        {**PARANA, "subtype": "municipality"},
        {**PARANA, "subtype": "planet"},
        {"source": "gadm", "src_id": "BRA"},
    ],
    ids=["admin-level-3", "unknown", "no-subtype"],
)
async def test_an_unsupported_area_never_reaches_the_api(aoi):
    handler = FakeHandler()

    with pytest.raises(UnsupportedAreaError):
        await _list(handler, aoi=aoi)

    assert handler.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "aoi",
    [
        {"source": "gadm", "src_id": "BRA", "subtype": "country"},
        {
            "source": "kba",
            "src_id": "8111",
            "subtype": "key-biodiversity-area",
        },
        {
            "source": "custom",
            "src_id": "5f0c1c4e-0000-4000-8000-000000000000",
            "subtype": "custom-area",
        },
    ],
    ids=["country", "kba", "custom-area"],
)
async def test_other_area_types_are_supported(aoi):
    handler = FakeHandler()

    await _list(handler, aoi=aoi)

    assert len(handler.calls) == 1


@pytest.mark.asyncio
async def test_a_failed_pull_raises_with_the_upstream_message():
    handler = FakeHandler(
        DataPullResult(success=False, data=None, message="timed out")
    )

    with pytest.raises(AlertsUnavailableError, match="timed out"):
        await _list(handler)


@pytest.mark.asyncio
async def test_a_result_it_cannot_read_is_unavailable():
    data = _rows(("2026-10-09", "nominal", 1.0))
    handler = FakeHandler(DataPullResult(success=True, data=data, message=""))

    with pytest.raises(AlertsUnavailableError, match="confidence"):
        await _list(handler)
