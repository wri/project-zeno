from datetime import date

from src.shared.imagery.planet import MonthlyPeriod


def test_monthly_period_starts_on_the_first_day_of_its_month():
    assert MonthlyPeriod.from_month("2026-08").start == date(2026, 8, 1)


def test_monthly_period_start_follows_the_requested_month():
    assert MonthlyPeriod.from_month("2025-12").start == date(2025, 12, 1)


def test_monthly_period_ends_on_the_last_day_of_its_month():
    assert MonthlyPeriod.from_month("2026-08").end == date(2026, 8, 31)


def test_monthly_period_for_december_ends_on_the_last_day_of_that_year():
    assert MonthlyPeriod.from_month("2025-12").end == date(2025, 12, 31)


def test_monthly_period_survives_a_json_round_trip_unchanged():
    period = MonthlyPeriod.from_month("2026-08")

    assert (
        MonthlyPeriod.model_validate_json(period.model_dump_json()) == period
    )
