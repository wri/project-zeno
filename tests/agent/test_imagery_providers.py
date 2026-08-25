"""Unit tests for imagery provider implementations."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from cogeo_mosaic.errors import MosaicNotFoundError

from src.agent.imagery.base import ImageryRequest
from src.agent.imagery.planet import PlanetImageryProvider
from src.agent.imagery.sentinel2 import Sentinel2ImageryProvider
from src.api.services.mosaic import MosaicResult

PLANET_AOIS = [
    {
        "name": "Planet test area",
        "source": "custom",
        "src_id": "planet-test",
        "bbox": [-69.5, -1.0, -69.0, -0.5],
    }
]


@pytest.mark.asyncio
async def test_planet_provider_builds_monthly_imagery():
    provider = PlanetImageryProvider()
    request = ImageryRequest(
        aois=PLANET_AOIS,
        target_date=date(2025, 6, 15),
        language="en",
    )

    result = await provider.get_imagery(request)

    assert provider.covers(PLANET_AOIS)
    assert result.status == "success"
    assert result.imagery.provider == "planet"
    assert result.imagery.mosaic_id == "planet:2025-06"
    assert result.imagery.start_date == "2025-06-01"
    assert result.imagery.end_date == "2025-06-30"
    assert "June 1–30, 2025" in result.message


@pytest.mark.asyncio
async def test_planet_provider_combines_aoi_bounds():
    provider = PlanetImageryProvider()
    request = ImageryRequest(
        aois=[
            {**PLANET_AOIS[0], "bbox": [-69.5, -2.0, -68.0, -0.5]},
            {**PLANET_AOIS[0], "bbox": [-67.0, -4.0, -66.0, -1.0]},
        ],
        target_date=date(2025, 6, 15),
        language="en",
    )

    result = await provider.get_imagery(request)

    assert result.imagery.bounds == [-69.5, -4.0, -66.0, -0.5]


@pytest.mark.asyncio
async def test_sentinel_provider_builds_imagery_from_mosaic_result():
    provider = Sentinel2ImageryProvider()
    request = ImageryRequest(
        aois=[{"name": "Zurich", "source": "gadm", "src_id": "CHE.26_1"}],
        target_date=date(2025, 6, 1),
        language="en",
    )
    mosaic = MosaicResult(
        mosaic_id="abc123",
        item_count=1,
        date_start=date(2025, 5, 20),
        date_end=date(2025, 6, 10),
    )

    with patch(
        "src.agent.imagery.sentinel2.create_sentinel2_mosaic",
        new_callable=AsyncMock,
        return_value=mosaic,
    ) as create:
        result = await provider.get_imagery(request)

    recipe = create.call_args.args[0]
    assert recipe.target_date == date(2025, 6, 1)
    assert result.imagery.provider == "sentinel-2"
    assert result.imagery.mosaic_id == "abc123"
    assert result.imagery.start_date == "2025-05-20"
    assert result.imagery.end_date == "2025-06-10"


@pytest.mark.asyncio
async def test_sentinel_provider_returns_error_status_for_geometry_failure():
    provider = Sentinel2ImageryProvider()
    request = ImageryRequest(
        aois=[{"name": "Zurich", "source": "gadm", "src_id": "CHE.26_1"}],
        target_date=None,
        language="en",
    )

    with patch(
        "src.agent.imagery.sentinel2.create_sentinel2_mosaic",
        new_callable=AsyncMock,
        side_effect=MosaicNotFoundError(),
    ):
        result = await provider.get_imagery(request)

    assert result.status == "error"
    assert result.imagery is None
    assert "geometry" in result.message.lower()
