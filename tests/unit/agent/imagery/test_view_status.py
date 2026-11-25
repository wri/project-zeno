"""How the agent reads the map's imagery report (view_context)."""

from src.agent.imagery_view_status import (
    describe_imagery,
    find_imagery,
    imagery_result,
)
from src.agent.middleware import format_session_block
from src.agent.tools.inspect_view_context import format_view_context

ENTRY = {
    "imagery_id": "tok",
    "provider": "sentinel-2",
    "render": "client",
    "status": "ok",
    "aoi_names": ["Jaru"],
    "target_date": "2026-11-10",
    "window_days": 7,
    "max_cloud_cover": 20,
    "item_count": 9,
    "start_date": "2026-11-08",
    "end_date": "2026-11-12",
}


def test_result_gives_count_and_dates():
    assert imagery_result(ENTRY) == "9 scenes, 2026-11-08 to 2026-11-12"
    single = {**ENTRY, "item_count": 1, "end_date": "2026-11-08"}
    assert imagery_result(single) == "1 scene, 2026-11-08"


def test_result_explains_an_empty_or_failed_search():
    assert "no scenes" in imagery_result({**ENTRY, "status": "no_scenes"})
    assert "too large" in imagery_result({**ENTRY, "status": "too_large"})
    assert "failed" in imagery_result({**ENTRY, "status": "error"})


def test_describe_names_the_request_and_result():
    assert describe_imagery(ENTRY) == (
        "sentinel-2 around 2026-11-10 (Jaru; ±7 days; <20% cloud): "
        "9 scenes, 2026-11-08 to 2026-11-12"
    )


def test_find_matches_by_token():
    view = {"visible_imagery": [ENTRY, {**ENTRY, "imagery_id": "other"}]}
    assert find_imagery(view, "tok") is ENTRY
    assert find_imagery(view, "missing") is None
    assert find_imagery(None, "tok") is None


def _state(view):
    return {
        "imagery": {
            "provider": "sentinel-2",
            "render": "client",
            "mosaic_id": "tok",
            "target_date": "2026-11-10",
            "aoi_names": ["Jaru"],
        },
        "view_context": view,
    }


def test_session_line_carries_the_map_result():
    block = format_session_block(
        _state({"page": "map", "visible_imagery": [ENTRY]})
    )
    assert (
        "Imagery: sentinel-2 around 2026-11-10 (map: 9 scenes, "
        "2026-11-08 to 2026-11-12)" in block
    )


def test_session_line_before_the_map_reports():
    block = format_session_block(_state({"page": "map"}))
    assert "Imagery: sentinel-2 around 2026-11-10 (no map report" in block


def test_session_line_for_tiler_imagery_keeps_the_scene_count():
    state = {
        "imagery": {
            "provider": "planet",
            "target_date": "2026-08-15",
            "item_count": 3,
        }
    }
    assert "Imagery: planet around 2026-08-15 (3 scenes)" in (
        format_session_block(state)
    )


def test_inspect_view_context_lists_imagery_not_under_other():
    text = format_view_context({"page": "map", "visible_imagery": [ENTRY]})
    assert "- Imagery on the map (1):" in text
    assert "9 scenes, 2026-11-08 to 2026-11-12" in text
    assert "Other" not in text
