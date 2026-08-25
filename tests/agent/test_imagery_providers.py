"""Unit tests for imagery provider implementations."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from cogeo_mosaic.errors import MosaicNotFoundError

from src.agent.imagery.base import ImageryRequest
from src.agent.imagery.planet import PlanetImageryProvider
from src.agent.imagery.sentinel2 import Sentinel2ImageryProvider
from src.api.services.mosaic import (
    AoiTooLargeError,
    MosaicResult,
    NoScenesFoundError,
)

PLANET_AOIS = [
    {
        "name": "Planet test area",
        "source": "custom",
        "src_id": "planet-test",
        "bbox": [-69.5, -1.0, -69.0, -0.5],
    }
]
SENTINEL_AOIS = [{"name": "Zurich", "source": "gadm", "src_id": "CHE.26_1"}]


def _request(aois=PLANET_AOIS, target=date(2025, 6, 15), **kwargs):
    return ImageryRequest(
        aois=aois, target_date=target, language="en", **kwargs
    )


@pytest.mark.asyncio
async def test_planet_provider_builds_monthly_imagery():
    provider = PlanetImageryProvider()

    result = await provider.get_imagery(_request())

    assert provider.covers(PLANET_AOIS)
    assert result.status == "success"
    assert result.imagery.model_dump(exclude_none=True) == {
        "provider": "planet",
        "tile_url": (
            "https://tiles.globalforestwatch.org/"
            "integrated_alerts_planet_imagery/{z}/{x}/{y}.png?month=2025-06"
        ),
        "bounds": [-69.5, -1.0, -69.0, -0.5],
        "min_zoom": 5,
        "max_zoom": 15,
        "mosaic_id": "planet:2025-06",
        "start_date": "2025-06-01",
        "end_date": "2025-06-30",
        "target_date": "2025-06-15",
        "aoi_names": ["Planet test area"],
    }
    assert "June 1–30, 2025" in result.message


def test_planet_date_and_coverage_rules():
    provider = PlanetImageryProvider()
    today = date(2026, 8, 25)

    assert provider.month(None, today=today) == "2026-07"
    assert provider.month(None, today=date(2026, 1, 3)) == "2025-12"
    assert not provider.is_newer_than_last_full_month(
        date(2026, 7, 31), today=today
    )
    assert provider.is_newer_than_last_full_month(
        date(2026, 8, 1), today=today
    )
    assert not provider.covers(SENTINEL_AOIS)


@pytest.mark.asyncio
async def test_planet_provider_combines_aoi_bounds():
    aois = [
        {**PLANET_AOIS[0], "bbox": [-69.5, -2.0, -68.0, -0.5]},
        {**PLANET_AOIS[0], "bbox": [-67.0, -4.0, -66.0, -1.0]},
    ]

    result = await PlanetImageryProvider().get_imagery(_request(aois=aois))

    assert result.imagery.bounds == [-69.5, -4.0, -66.0, -0.5]


@pytest.mark.asyncio
async def test_sentinel_provider_builds_imagery_and_recipe():
    mosaic = MosaicResult(
        mosaic_id="abc123",
        item_count=4,
        date_start=date(2025, 5, 20),
        date_end=date(2025, 6, 10),
        mean_cloud_cover=7.35,
        min_cloud_cover=2.1,
        max_cloud_cover=14.8,
    )
    create = AsyncMock(return_value=mosaic)

    with patch("src.agent.imagery.sentinel2.create_sentinel2_mosaic", create):
        result = await Sentinel2ImageryProvider().get_imagery(
            _request(
                aois=SENTINEL_AOIS,
                target=date(2025, 6, 1),
                window_days=60,
                max_cloud_cover=500,
            )
        )

    recipe = create.call_args.args[0]
    assert recipe.aois == (("gadm", "CHE.26_1"),)
    assert recipe.target_date == date(2025, 6, 1)
    assert recipe.window_days == 60
    assert recipe.max_cloud_cover == 100
    assert result.status == "success"
    assert result.imagery.mosaic_id == "abc123"
    assert result.imagery.start_date == "2025-05-20"
    assert result.imagery.end_date == "2025-06-10"
    assert result.imagery.mean_cloud_cover == 7.35
    assert result.imagery.min_cloud_cover == 2.1
    assert result.imagery.max_cloud_cover_observed == 14.8


@pytest.mark.asyncio
async def test_sentinel_provider_defaults_to_previous_two_weeks():
    create = AsyncMock(
        return_value=MosaicResult(mosaic_id="abc123", item_count=1)
    )

    with patch("src.agent.imagery.sentinel2.create_sentinel2_mosaic", create):
        await Sentinel2ImageryProvider().get_imagery(
            _request(aois=SENTINEL_AOIS, target=None)
        )

    recipe = create.call_args.args[0]
    assert recipe.target_date == date.today() - timedelta(days=7)
    assert recipe.window_days == 7
    assert recipe.max_cloud_cover == 20


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (MosaicNotFoundError(), "geometry"),
        (AoiTooLargeError(123456.0), "too large"),
        (NoScenesFoundError(), "window_days"),
    ],
)
async def test_sentinel_provider_translates_expected_errors(error, expected):
    create = AsyncMock(side_effect=error)

    with patch("src.agent.imagery.sentinel2.create_sentinel2_mosaic", create):
        result = await Sentinel2ImageryProvider().get_imagery(
            _request(aois=SENTINEL_AOIS)
        )

    assert result.status == "error"
    assert result.imagery is None
    assert expected in result.message.lower()
