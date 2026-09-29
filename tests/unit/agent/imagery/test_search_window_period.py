from datetime import date

from src.shared.imagery.sentinel2 import SearchWindowPeriod


def test_search_window_period_starts_window_days_before_the_target_date():
    period = SearchWindowPeriod.from_search(
        date(2026, 8, 15), window_days=7, today=date(2026, 9, 29)
    )

    assert period.start == date(2026, 8, 8)


def test_search_window_period_start_follows_the_target_date_and_window():
    period = SearchWindowPeriod.from_search(
        date(2026, 1, 10), window_days=30, today=date(2026, 9, 29)
    )

    assert period.start == date(2025, 12, 11)


def test_search_window_period_ends_window_days_after_the_target_date():
    period = SearchWindowPeriod.from_search(
        date(2026, 8, 15), window_days=7, today=date(2026, 9, 29)
    )

    assert period.end == date(2026, 8, 22)


def test_search_window_period_end_follows_the_target_date_and_window():
    period = SearchWindowPeriod.from_search(
        date(2026, 1, 10), window_days=30, today=date(2026, 9, 29)
    )

    assert period.end == date(2026, 2, 9)


def test_search_window_period_never_ends_after_the_day_the_search_ran():
    period = SearchWindowPeriod.from_search(
        date(2026, 9, 25), window_days=7, today=date(2026, 9, 29)
    )

    assert period.end == date(2026, 9, 29)
