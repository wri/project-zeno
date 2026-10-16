import copy
from datetime import date

import pytest

from src.api.services.alerts_list import (
    AlertDay,
    UnexpectedAlertsDataError,
    alert_days,
)

WEEK = (date(2026, 10, 4), date(2026, 10, 10))


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
