from src.agent.middleware import format_session_block
from tests.unit.agent.imagery.factories import (
    planet_imagery,
    sentinel2_imagery,
)


def test_session_block_describes_planet_imagery_by_its_period():
    state = {"imagery": planet_imagery().model_dump(mode="json")}

    assert "Imagery: planet 2026-08-01 → 2026-08-31" in format_session_block(
        state
    )


def test_session_block_mentions_how_many_scenes_sentinel2_imagery_has():
    state = {"imagery": sentinel2_imagery().model_dump(mode="json")}

    assert (
        "Imagery: sentinel-2 2026-08-08 → 2026-08-22 (9 scenes)"
        in format_session_block(state)
    )


def test_session_block_omits_the_scene_count_when_sentinel2_has_no_scene_summary():
    state = {"imagery": sentinel2_imagery(scenes=None).model_dump(mode="json")}

    lines = format_session_block(state).splitlines()

    assert "Imagery: sentinel-2 2026-08-08 → 2026-08-22" in lines
