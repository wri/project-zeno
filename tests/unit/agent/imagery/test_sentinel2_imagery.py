import pytest
from pydantic import ValidationError

from src.shared.imagery.sentinel2 import Sentinel2Imagery
from tests.unit.agent.imagery.factories import scene_summary, sentinel2_imagery


def test_sentinel2_imagery_identifies_its_provider_as_sentinel_2():
    assert sentinel2_imagery().provider == "sentinel-2"


def test_sentinel2_imagery_keeps_the_mosaic_it_renders_from():
    imagery = sentinel2_imagery(
        tile_url="https://tiles.example/mosaic/{z}/{x}/{y}.png",
        tilejson_url="https://tiles.example/mosaic/tilejson.json",
        mosaic_id="abc123",
    )

    assert imagery.tile_url == "https://tiles.example/mosaic/{z}/{x}/{y}.png"
    assert imagery.tilejson_url == "https://tiles.example/mosaic/tilejson.json"
    assert imagery.mosaic_id == "abc123"


def test_sentinel2_imagery_keeps_the_cloud_cover_limit_it_searched_with():
    assert sentinel2_imagery(max_cloud_cover=50).max_cloud_cover == 50


def test_sentinel2_imagery_carries_the_summary_of_its_scenes():
    summary = scene_summary(item_count=12)

    assert sentinel2_imagery(scenes=summary).scenes == summary


def test_sentinel2_imagery_from_an_old_cached_mosaic_has_no_scene_summary():
    assert sentinel2_imagery(scenes=None).scenes is None


def test_sentinel2_imagery_must_say_whether_it_has_a_scene_summary():
    imagery = sentinel2_imagery().model_dump()
    del imagery["scenes"]

    with pytest.raises(ValidationError, match="scenes"):
        Sentinel2Imagery.model_validate(imagery)
