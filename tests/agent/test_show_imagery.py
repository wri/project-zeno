"""Tests for the show_imagery agent tool."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.tools.show_imagery import PLANET_PROVIDER, show_imagery
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
        "src.agent.imagery.sentinel2.create_sentinel2_mosaic",
        new_callable=AsyncMock,
        **kwargs,
    )


def test_target_date_is_required_but_nullable_in_tool_schema():
    schema = show_imagery.args_schema.model_json_schema()

    assert "target_date" in schema["required"]
    variants = schema["properties"]["target_date"]["anyOf"]
    assert {variant.get("type") for variant in variants} == {
        "string",
        "null",
    }


@pytest.mark.asyncio
async def test_show_imagery_requires_aoi():
    command = await show_imagery.coroutine(
        state={}, target_date=None, tool_call_id="t1"
    )
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
    assert imagery["start_date"] == "2025-05-20"
    assert imagery["end_date"] == "2025-06-10"
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
            target_date=None,
            window_days=60,
            max_cloud_cover=500,
            tool_call_id="t1",
        )

    recipe = mock_create.call_args.args[0]
    assert recipe.window_days == 60
    assert recipe.max_cloud_cover == 100  # clamped

    with _patch_create(return_value=result) as mock_create:
        await show_imagery.coroutine(
            state=AOI_STATE, target_date=None, tool_call_id="t1"
        )

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
        await show_imagery.coroutine(
            state=AOI_STATE, target_date=None, tool_call_id="t1"
        )

    assert mock_create.call_args.args[0].target_date == date.today()


@pytest.mark.asyncio
async def test_show_imagery_relays_aoi_too_large():
    with _patch_create(side_effect=AoiTooLargeError(123456.0)):
        command = await show_imagery.coroutine(
            state=AOI_STATE, target_date=None, tool_call_id="t1"
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
    with _patch_create() as mock_create:
        command = await show_imagery.coroutine(
            state=PLANET_AOI_STATE,
            target_date="2025-06-15",
            tool_call_id="t1",
        )

    mock_create.assert_not_awaited()
    imagery = command.update["imagery"]
    assert imagery["provider"] == "planet"
    assert imagery["mosaic_id"] == "planet:2025-06"
    assert imagery["tile_url"] == (
        "http://127.0.0.1:8899/integrated_alerts_planet_imagery/"
        "{z}/{x}/{y}.png?month=2025-06"
    )
    assert imagery["window_days"] is None
    assert imagery["max_cloud_cover"] is None
    assert imagery["bounds"] == [-69.5, -1.0, -69.0, -0.5]
    assert imagery["min_zoom"] == 5
    assert imagery["max_zoom"] == 15
    assert imagery["start_date"] == "2025-06-01"
    assert imagery["end_date"] == "2025-06-30"
    assert "June 1–30, 2025" in _messages(command)[0].content
    assert "Sentinel-2" in _messages(command)[0].content


@pytest.mark.asyncio
async def test_show_imagery_explicit_sentinel_skips_planet():
    result = MosaicResult(mosaic_id="abc123", item_count=1)

    with _patch_create(return_value=result):
        command = await show_imagery.coroutine(
            state=PLANET_AOI_STATE,
            provider="sentinel-2",
            target_date="2025-06-15",
            tool_call_id="t1",
        )

    assert command.update["imagery"]["provider"] == "sentinel-2"


def test_planet_month_defaults_to_previous_full_month():
    assert PLANET_PROVIDER.month(None, today=date(2026, 8, 24)) == "2026-07"
    assert PLANET_PROVIDER.month(None, today=date(2026, 1, 3)) == "2025-12"


def test_recency_boundary_is_after_previous_full_month():
    today = date(2026, 8, 25)

    assert not PLANET_PROVIDER.is_newer_than_last_full_month(None, today=today)
    assert not PLANET_PROVIDER.is_newer_than_last_full_month(
        date(2026, 7, 31), today=today
    )
    assert PLANET_PROVIDER.is_newer_than_last_full_month(
        date(2026, 8, 1), today=today
    )


@pytest.mark.asyncio
async def test_omitted_date_still_defaults_to_planet_in_coverage():
    with _patch_create() as mock_create:
        command = await show_imagery.coroutine(
            state=PLANET_AOI_STATE, target_date=None, tool_call_id="t1"
        )

    mock_create.assert_not_awaited()
    assert command.update["imagery"]["provider"] == "planet"


@pytest.mark.asyncio
async def test_recent_date_defaults_to_sentinel_in_planet_coverage():
    result = MosaicResult(mosaic_id="abc123", item_count=1)

    with (
        patch.object(
            PLANET_PROVIDER,
            "is_newer_than_last_full_month",
            return_value=True,
        ),
        _patch_create(return_value=result),
    ):
        command = await show_imagery.coroutine(
            state=PLANET_AOI_STATE,
            target_date="2026-08-15",
            tool_call_id="t1",
        )

    assert command.update["imagery"]["provider"] == "sentinel-2"


@pytest.mark.asyncio
async def test_explicit_planet_overrides_recent_date_preference():
    with (
        patch.object(
            PLANET_PROVIDER,
            "is_newer_than_last_full_month",
            return_value=True,
        ),
        _patch_create() as mock_create,
    ):
        command = await show_imagery.coroutine(
            state=PLANET_AOI_STATE,
            provider="planet",
            target_date="2026-08-15",
            tool_call_id="t1",
        )

    mock_create.assert_not_awaited()
    assert command.update["imagery"]["provider"] == "planet"


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
