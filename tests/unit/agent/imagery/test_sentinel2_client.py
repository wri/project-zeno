"""Sentinel-2 imagery is a request for the browser: no I/O on the server."""

from datetime import date, timedelta
from unittest.mock import patch

from src.agent.imagery import ImageryRequest, Sentinel2ImageryProvider
from src.shared.imagery_recipe import decode_recipe

AOI = {"source": "gadm", "src_id": "BRA.22.25_2", "name": "Jaru"}


def request(**overrides) -> ImageryRequest:
    values = {
        "aois": [AOI],
        "target_date": date(2026, 11, 10),
        "language": "en",
    }
    values.update(overrides)
    return ImageryRequest(**values)


async def test_writes_a_client_recipe_and_no_tile_url():
    result = await Sentinel2ImageryProvider().get_imagery(
        request(window_days=30, max_cloud_cover=50)
    )
    assert result.status == "success"
    imagery = result.imagery
    assert imagery.render == "client"
    assert imagery.tile_url is None
    assert imagery.item_count is None
    assert imagery.aoi_names == ["Jaru"]
    assert (imagery.target_date, imagery.window_days) == ("2026-11-10", 30)
    assert imagery.max_cloud_cover == 50
    recipe = decode_recipe(imagery.mosaic_id)
    assert recipe.aois == (("gadm", "BRA.22.25_2"),)
    assert recipe.target_date == date(2026, 11, 10)
    assert (recipe.window_days, recipe.max_cloud_cover) == (30, 50)


async def test_message_states_the_request_not_a_scene_count():
    result = await Sentinel2ImageryProvider().get_imagery(request())
    assert result.message == (
        "Sentinel-2 imagery for Jaru around 2026-11-10 (±7 days, under 50% "
        "cloud cover) is shown on the map."
    )


async def test_defaults_to_the_past_two_weeks():
    imagery = (
        await Sentinel2ImageryProvider().get_imagery(request(target_date=None))
    ).imagery
    assert (
        imagery.target_date == (date.today() - timedelta(days=7)).isoformat()
    )
    assert (imagery.window_days, imagery.max_cloud_cover) == (7, 50)


async def test_clamps_the_search_parameters():
    imagery = (
        await Sentinel2ImageryProvider().get_imagery(
            request(window_days=400, max_cloud_cover=0)
        )
    ).imagery
    assert (imagery.window_days, imagery.max_cloud_cover) == (183, 1)


async def test_custom_areas_carry_their_owner():
    custom = {"source": "custom", "src_id": "area-1", "name": "My area"}
    with patch(
        "src.agent.imagery.sentinel2.current_user_id", return_value="u-9"
    ):
        imagery = (
            await Sentinel2ImageryProvider().get_imagery(
                request(aois=[custom])
            )
        ).imagery
    assert decode_recipe(imagery.mosaic_id).user_id == "u-9"


async def test_numeric_src_ids_are_written_as_strings():
    numeric = {"source": "wdpa", "src_id": 555555, "name": "Paracas"}
    imagery = (
        await Sentinel2ImageryProvider().get_imagery(request(aois=[numeric]))
    ).imagery
    assert decode_recipe(imagery.mosaic_id).aois == (("wdpa", "555555"),)
