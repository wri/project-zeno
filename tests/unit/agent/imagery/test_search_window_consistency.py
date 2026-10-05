from datetime import date

import pytest

from src.api.services.mosaic import MosaicRecipe, search_window
from src.shared.imagery.sentinel2 import SearchWindowPeriod

TODAY = date(2026, 9, 29)


@pytest.mark.parametrize(
    ("target_date", "window_days"),
    [(date(2025, 6, 1), 7), (date(2026, 9, 25), 7)],
    ids=["window in the past", "window running past today"],
)
def test_the_mosaic_searches_the_same_window_the_sentinel2_period_reports(
    target_date, window_days
):
    recipe = MosaicRecipe(
        aois=(("gadm", "CHE.26_1"),),
        target_date=target_date,
        window_days=window_days,
        max_cloud_cover=20,
    )
    period = SearchWindowPeriod.from_search(
        target_date, window_days, today=TODAY
    )

    assert search_window(recipe, TODAY) == (period.start, period.end)
