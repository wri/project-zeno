"""Tests for the show_imagery agent tool."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.tools.show_imagery import show_imagery
from src.api.services.mosaic import AoiTooLargeError, MosaicResult

AOI_STATE = {
    "aoi_selection": {
        "name": "Zurich",
        "aois": [{"name": "Zurich", "source": "gadm", "src_id": "CHE.26_1"}],
    }
}


def _messages(command):
    return command.update["messages"]


def _patch_create(**kwargs):
    return patch(
        "src.agent.tools.show_imagery.create_sentinel2_mosaic",
        new_callable=AsyncMock,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_show_imagery_requires_aoi():
    command = await show_imagery.coroutine(state={}, tool_call_id="t1")
    assert "No AOI selected" in _messages(command)[0].content
    assert "imagery" not in command.update


@pytest.mark.asyncio
async def test_show_imagery_rejects_invalid_date():
    command = await show_imagery.coroutine(
        state=AOI_STATE, target_date="June 2025", tool_call_id="t1"
    )
    assert "Invalid target_date" in _messages(command)[0].content


@pytest.mark.asyncio
async def test_show_imagery_success():
    result = MosaicResult(
        mosaic_id="abc123",
        item_count=4,
        date_start=date(2025, 5, 20),
        date_end=date(2025, 6, 10),
    )

    with _patch_create(return_value=result) as mock_create:
        command = await show_imagery.coroutine(
            state=AOI_STATE, target_date="2025-06-01", tool_call_id="t1"
        )

    recipe = mock_create.call_args.args[0]
    assert recipe.aois == (("gadm", "CHE.26_1"),)
    assert recipe.target_date == date(2025, 6, 1)
    assert recipe.user_id is None

    imagery = command.update["imagery"]
    assert imagery["mosaic_id"] == "abc123"
    assert imagery["tile_url"].endswith("?url=abc123")
    assert imagery["target_date"] == "2025-06-01"
    assert imagery["window_days"] == 7
    assert imagery["max_cloud_cover"] == 20
    assert imagery["aoi_names"] == ["Zurich"]
    assert "4 scenes" in _messages(command)[0].content


@pytest.mark.asyncio
async def test_show_imagery_passes_and_clamps_search_parameters():
    result = MosaicResult(
        mosaic_id="abc123",
        item_count=1,
        date_start=date(2025, 5, 20),
        date_end=date(2025, 6, 10),
    )

    with _patch_create(return_value=result) as mock_create:
        await show_imagery.coroutine(
            state=AOI_STATE,
            window_days=60,
            max_cloud_cover=500,
            tool_call_id="t1",
        )

    recipe = mock_create.call_args.args[0]
    assert recipe.window_days == 60
    assert recipe.max_cloud_cover == 100  # clamped

    with _patch_create(return_value=result) as mock_create:
        await show_imagery.coroutine(state=AOI_STATE, tool_call_id="t1")

    recipe = mock_create.call_args.args[0]
    assert recipe.window_days == 7
    assert recipe.max_cloud_cover == 20


@pytest.mark.asyncio
async def test_show_imagery_no_scenes_suggests_loosening():
    from src.api.services.mosaic import NoScenesFoundError

    with _patch_create(side_effect=NoScenesFoundError()):
        command = await show_imagery.coroutine(
            state=AOI_STATE, target_date="2025-07-15", tool_call_id="t1"
        )

    message = _messages(command)[0]
    assert "±7 days" in message.content
    assert "20%" in message.content
    assert "window_days" in message.content
    assert "max_cloud_cover" in message.content
    assert message.response_metadata["msg_type"] == "human_feedback"


@pytest.mark.asyncio
async def test_show_imagery_freezes_default_date():
    """Without target_date the recipe must carry today's resolved date."""
    result = MosaicResult(
        mosaic_id="abc123",
        item_count=1,
        date_start=date(2025, 5, 20),
        date_end=date(2025, 6, 10),
    )

    with _patch_create(return_value=result) as mock_create:
        await show_imagery.coroutine(state=AOI_STATE, tool_call_id="t1")

    assert mock_create.call_args.args[0].target_date == date.today()


@pytest.mark.asyncio
async def test_show_imagery_relays_aoi_too_large():
    with _patch_create(side_effect=AoiTooLargeError(123456.0)):
        command = await show_imagery.coroutine(
            state=AOI_STATE, tool_call_id="t1"
        )

    message = _messages(command)[0]
    assert "too large" in message.content
    assert message.response_metadata["msg_type"] == "human_feedback"
    assert "imagery" not in command.update
