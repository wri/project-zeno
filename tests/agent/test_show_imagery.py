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

PLANET_AOI_STATE = {
    "aoi_selection": {
        "name": "Planet test area",
        "aois": [
            {
                "name": "Planet test area",
                "source": "custom",
                "src_id": "planet-test",
                "bbox": [-69.5, -1.0, -69.0, -0.5],
            }
        ],
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
    # The tool passes the MosaicResult's external titiler URLs through.
    assert imagery["tile_url"] == result.tile_url
    assert imagery["tilejson_url"] == result.tilejson_url
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


@pytest.mark.asyncio
async def test_show_imagery_carries_cloud_cover():
    """Cloud cover stats from MosaicResult are threaded into ImageryState."""
    result = MosaicResult(
        mosaic_id="abc123",
        item_count=4,
        date_start=date(2025, 5, 20),
        date_end=date(2025, 6, 10),
        mean_cloud_cover=7.35,
        min_cloud_cover=2.1,
        max_cloud_cover=14.8,
    )

    with _patch_create(return_value=result):
        command = await show_imagery.coroutine(
            state=AOI_STATE, target_date="2025-06-01", tool_call_id="t1"
        )

    imagery = command.update["imagery"]
    assert imagery["mean_cloud_cover"] == 7.35
    assert imagery["min_cloud_cover"] == 2.1
    assert imagery["max_cloud_cover_observed"] == 14.8
    assert imagery["max_cloud_cover"] == 20  # from recipe (search threshold)


@pytest.mark.asyncio
async def test_show_imagery_defaults_to_planet_in_coverage():
    mosaics = [
        {
            "name": "planet_medres_visual_2025-06_mosaic",
            "first_acquired": "2025-06-01T00:00:00.000Z",
            "last_acquired": "2025-07-01T00:00:00.000Z",
        }
    ]

    with (
        patch(
            "src.agent.tools.show_imagery._fetch_planet_mosaics",
            new_callable=AsyncMock,
            return_value=mosaics,
        ),
        _patch_create() as mock_create,
    ):
        command = await show_imagery.coroutine(
            state=PLANET_AOI_STATE,
            target_date="2025-06-15",
            tool_call_id="t1",
        )

    mock_create.assert_not_awaited()
    imagery = command.update["imagery"]
    assert imagery["provider"] == "planet"
    assert imagery["mosaic_id"] == "planet_medres_visual_2025-06_mosaic"
    assert imagery["tile_url"].endswith(
        "/wmts/v1/planet_medres_visual_2025-06_mosaic/{z}/{x}/{y}.png"
    )
    assert imagery["window_days"] is None
    assert imagery["max_cloud_cover"] is None
    assert "Sentinel-2" in _messages(command)[0].content


@pytest.mark.asyncio
async def test_show_imagery_explicit_sentinel_skips_planet():
    result = MosaicResult(mosaic_id="abc123", item_count=1)

    with (
        patch(
            "src.agent.tools.show_imagery._fetch_planet_mosaics",
            new_callable=AsyncMock,
        ) as fetch_planet,
        _patch_create(return_value=result),
    ):
        command = await show_imagery.coroutine(
            state=PLANET_AOI_STATE,
            provider="sentinel-2",
            target_date="2025-06-15",
            tool_call_id="t1",
        )

    fetch_planet.assert_not_awaited()
    assert command.update["imagery"]["provider"] == "sentinel-2"


@pytest.mark.asyncio
async def test_show_imagery_falls_back_when_planet_month_unavailable():
    result = MosaicResult(mosaic_id="abc123", item_count=1)

    with (
        patch(
            "src.agent.tools.show_imagery._fetch_planet_mosaics",
            new_callable=AsyncMock,
            return_value=[],
        ),
        _patch_create(return_value=result) as mock_create,
    ):
        command = await show_imagery.coroutine(
            state=PLANET_AOI_STATE,
            target_date="2025-06-15",
            tool_call_id="t1",
        )

    mock_create.assert_awaited_once()
    assert command.update["imagery"]["provider"] == "sentinel-2"


@pytest.mark.asyncio
async def test_explicit_planet_outside_coverage_does_not_build_sentinel():
    with _patch_create() as mock_create:
        command = await show_imagery.coroutine(
            state=AOI_STATE,
            provider="planet",
            target_date="2025-06-15",
            tool_call_id="t1",
        )

    mock_create.assert_not_awaited()
    assert "not available" in _messages(command)[0].content
    assert "imagery" not in command.update
