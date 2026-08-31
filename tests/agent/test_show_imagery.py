"""Unit tests for the Sentinel-2 imagery tool."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agent.imagery import ImageryProviderResult
from src.agent.models import ImageryState
from src.agent.tools.show_imagery import SENTINEL2_PROVIDER, show_imagery

AOI_STATE = {
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


def _result() -> ImageryProviderResult:
    return ImageryProviderResult(
        status="success",
        message="Showing sentinel-2",
        imagery=ImageryState(
            provider="sentinel-2",
            tile_url="https://example.com/{z}/{x}/{y}.png",
            mosaic_id="test-mosaic",
            aoi_names=["Test area"],
        ),
    )


def _message(command):
    return command.update["messages"][0].content


def test_tool_exposes_no_provider_choice():
    """Planet is opt-in via show_planet_imagery; this tool must not offer it."""
    schema = show_imagery.args_schema.model_json_schema()

    assert "provider" not in schema["properties"]
    assert "planet" not in (show_imagery.description or "").lower()


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
        (AOI_STATE, "June 2025", "Invalid target_date"),
    ],
)
async def test_show_imagery_rejects_invalid_input(state, target_date, message):
    command = await show_imagery.coroutine(
        state=state, target_date=target_date, tool_call_id="t1"
    )

    assert message in _message(command)
    assert "imagery" not in command.update


@pytest.mark.asyncio
async def test_show_imagery_returns_the_sentinel_layer():
    sentinel = AsyncMock(return_value=_result())

    with patch.object(SENTINEL2_PROVIDER, "get_imagery", sentinel):
        command = await show_imagery.coroutine(
            state=AOI_STATE, target_date="2025-06-15", tool_call_id="t1"
        )

    assert command.update["imagery"]["provider"] == "sentinel-2"
    assert sentinel.await_count == 1


@pytest.mark.asyncio
async def test_tuning_parameters_reach_the_provider():
    sentinel = AsyncMock(return_value=_result())

    with patch.object(SENTINEL2_PROVIDER, "get_imagery", sentinel):
        await show_imagery.coroutine(
            state=AOI_STATE,
            target_date=None,
            window_days=30,
            max_cloud_cover=50,
            tool_call_id="t1",
        )

    request = sentinel.await_args.args[0]
    assert (request.window_days, request.max_cloud_cover) == (30, 50)
