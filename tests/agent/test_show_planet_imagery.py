"""Unit tests for the Planet-only imagery tool and its Sentinel-2 fallback."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.imagery import ImageryProviderResult
from src.agent.models import ImageryState
from src.agent.tools.show_planet_imagery import (
    PLANET_PROVIDER,
    SENTINEL2_PROVIDER,
    show_planet_imagery,
)

OUTSIDE_COVERAGE = {
    "aoi_selection": {
        "name": "Zurich",
        "aois": [{"name": "Zurich", "source": "gadm", "src_id": "CHE.26_1"}],
    }
}
IN_COVERAGE = {
    "aoi_selection": {
        "name": "Test area",
        "aois": [
            {
                "name": "Test area",
                "source": "custom",
                "src_id": "test-area",
                "bbox": [-69.5, -1.0, -69.0, -0.5],
            }
        ],
    }
}


def _result(provider: str) -> ImageryProviderResult:
    return ImageryProviderResult(
        status="success",
        message=f"Showing {provider}",
        imagery=ImageryState(
            provider=provider,
            tile_url="https://example.com/{z}/{x}/{y}.png",
            mosaic_id="test-mosaic",
            aoi_names=["Test area"],
        ),
    )


def _message(command):
    return command.update["messages"][0].content


@pytest.mark.asyncio
async def test_planet_shown_inside_coverage():
    planet = AsyncMock(return_value=_result("planet"))

    with patch.object(PLANET_PROVIDER, "get_imagery", planet):
        command = await show_planet_imagery.coroutine(
            state=IN_COVERAGE, target_date="2025-06-15", tool_call_id="t1"
        )

    assert command.update["imagery"]["provider"] == "planet"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "target_date"),
    [
        (OUTSIDE_COVERAGE, "2025-06-15"),  # outside the footprint
        (IN_COVERAGE, date.today().isoformat()),  # month not yet complete
    ],
)
async def test_falls_back_to_sentinel_with_reason(state, target_date):
    planet = AsyncMock(return_value=_result("planet"))
    sentinel = AsyncMock(return_value=_result("sentinel-2"))

    with (
        patch.object(PLANET_PROVIDER, "get_imagery", planet),
        patch.object(SENTINEL2_PROVIDER, "get_imagery", sentinel),
    ):
        command = await show_planet_imagery.coroutine(
            state=state, target_date=target_date, tool_call_id="t1"
        )

    assert command.update["imagery"]["provider"] == "sentinel-2"
    assert "not available" in _message(command)
    assert planet.await_count == 0


@pytest.mark.asyncio
async def test_fallback_reason_survives_a_sentinel_error():
    sentinel = AsyncMock(
        return_value=ImageryProviderResult(
            status="error", message="No scenes found."
        )
    )

    with patch.object(SENTINEL2_PROVIDER, "get_imagery", sentinel):
        command = await show_planet_imagery.coroutine(
            state=OUTSIDE_COVERAGE, target_date="2025-06-15", tool_call_id="t1"
        )

    assert "not available" in _message(command)
    assert "No scenes found." in _message(command)
