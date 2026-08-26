"""Unit tests for show_imagery routing and command construction."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.imagery import ImageryProviderResult
from src.agent.models import ImageryState
from src.agent.tools.show_imagery import (
    PLANET_PROVIDER,
    SENTINEL2_PROVIDER,
    show_imagery,
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


def test_target_date_is_optional_and_nullable_in_tool_schema():
    schema = show_imagery.args_schema.model_json_schema()

    assert "target_date" not in schema["required"]
    variants = schema["properties"]["target_date"]["anyOf"]
    assert {variant.get("type") for variant in variants} == {"string", "null"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "target_date", "message"),
    [
        ({}, None, "No AOI selected"),
        (OUTSIDE_COVERAGE, "June 2025", "Invalid target_date"),
    ],
)
async def test_show_imagery_rejects_invalid_input(state, target_date, message):
    command = await show_imagery.coroutine(
        state=state, target_date=target_date, tool_call_id="t1"
    )

    assert message in _message(command)
    assert "imagery" not in command.update


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "target_date", "expected"),
    [
        (None, "2025-06-15", "planet"),
        (None, None, "sentinel-2"),
        ("sentinel-2", "2025-06-15", "sentinel-2"),
        ("planet", None, "planet"),
        ("planet", date.today().isoformat(), "planet"),
    ],
)
async def test_show_imagery_routes_provider(provider, target_date, expected):
    planet = AsyncMock(return_value=_result("planet"))
    sentinel = AsyncMock(return_value=_result("sentinel-2"))

    with (
        patch.object(PLANET_PROVIDER, "get_imagery", planet),
        patch.object(SENTINEL2_PROVIDER, "get_imagery", sentinel),
    ):
        command = await show_imagery.coroutine(
            state=IN_COVERAGE,
            provider=provider,
            target_date=target_date,
            tool_call_id="t1",
        )

    assert command.update["imagery"]["provider"] == expected
    assert planet.await_count == (expected == "planet")
    assert sentinel.await_count == (expected == "sentinel-2")


@pytest.mark.asyncio
async def test_omitted_date_suggests_planet_when_available():
    sentinel = AsyncMock(return_value=_result("sentinel-2"))

    with patch.object(SENTINEL2_PROVIDER, "get_imagery", sentinel):
        command = await show_imagery.coroutine(
            state=IN_COVERAGE, target_date=None, tool_call_id="t1"
        )

    assert "previous complete month" in _message(command)


@pytest.mark.asyncio
async def test_explicit_planet_outside_coverage_falls_back_to_sentinel():
    sentinel = AsyncMock(return_value=_result("sentinel-2"))

    with patch.object(SENTINEL2_PROVIDER, "get_imagery", sentinel):
        command = await show_imagery.coroutine(
            state=OUTSIDE_COVERAGE,
            provider="planet",
            target_date="2025-06-15",
            tool_call_id="t1",
        )

    assert command.update["imagery"]["provider"] == "sentinel-2"
    assert "not available" in _message(command)


@pytest.mark.asyncio
async def test_planet_fallback_is_explained_when_sentinel_also_fails():
    sentinel = AsyncMock(
        return_value=ImageryProviderResult(
            status="error", message="No scenes found."
        )
    )

    with patch.object(SENTINEL2_PROVIDER, "get_imagery", sentinel):
        command = await show_imagery.coroutine(
            state=OUTSIDE_COVERAGE,
            provider="planet",
            target_date="2025-06-15",
            tool_call_id="t1",
        )

    assert "not available" in _message(command)
    assert "No scenes found." in _message(command)
