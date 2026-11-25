"""How the agent reads the map's imagery report (view_context)."""

from src.agent.middleware import format_session_block
from src.agent.tools.inspect_view_context import (
    describe_imagery,
    format_view_context,
)

ENTRY = {
    "imagery_id": "tok",
    "provider": "sentinel-2",
    "status": "ok",
    "aoi_names": ["Jaru"],
    "target_date": "2026-11-10",
    "window_days": 7,
    "max_cloud_cover": 50,
    "item_count": 9,
    "start_date": "2026-11-08",
    "end_date": "2026-11-12",
}


def test_describe_names_the_request_and_result():
    assert describe_imagery(ENTRY) == (
        "sentinel-2 around 2026-11-10 (Jaru; ±7 days; <50% cloud): "
        "9 scenes, 2026-11-08 to 2026-11-12"
    )
    single = {**ENTRY, "item_count": 1, "end_date": "2026-11-08"}
    assert describe_imagery(single).endswith(": 1 scene, 2026-11-08")


def test_describe_explains_an_empty_or_failed_search():
    assert "no scenes" in describe_imagery({**ENTRY, "status": "no_scenes"})
    assert "too large" in describe_imagery({**ENTRY, "status": "too_large"})
    assert "failed" in describe_imagery({**ENTRY, "status": "error"})


def test_inspect_view_context_lists_imagery_not_under_other():
    text = format_view_context({"page": "map", "visible_imagery": [ENTRY]})
    assert "- Imagery on the map (1):" in text
    assert "9 scenes, 2026-11-08 to 2026-11-12" in text
    assert "Other" not in text


def test_session_line_states_the_request():
    state = {
        "imagery": {
            "provider": "sentinel-2",
            "mosaic_id": "tok",
            "target_date": "2026-11-10",
            "window_days": 7,
            "max_cloud_cover": 50,
            "aoi_names": ["Jaru"],
        },
    }
    assert (
        "Imagery: sentinel-2 around 2026-11-10 (±7 days, <50% cloud)"
        in format_session_block(state)
    )


def test_session_line_for_planet_has_no_search_window():
    state = {"imagery": {"provider": "planet", "target_date": "2026-08-15"}}
    block = format_session_block(state)
    assert "Imagery: planet around 2026-08-15\n" in block + "\n"
