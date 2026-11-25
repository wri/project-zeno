"""What the map reports about the imagery it shows (view_context).

Sentinel-2 imagery is searched and drawn in the browser, so only the
frontend knows the scene search result. It sends one entry per visible
imagery capture in ``view_context.visible_imagery``::

    {"imagery_id": "<recipe token>", "provider": "sentinel-2",
     "render": "client", "status": "ok" | "no_scenes" | "too_large"
     | "error" | "searching", "aoi_names": [...], "target_date": ...,
     "window_days": 7, "max_cloud_cover": 20, "item_count": 9,
     "start_date": ..., "end_date": ...}

``imagery_id`` equals ``mosaic_id`` in the agent's imagery state, so the
agent can match its own show_imagery call to the map's result.
"""

from typing import Optional

_STATUS_TEXT = {
    "no_scenes": "no scenes found under the cloud limit in the window",
    "too_large": "area too large for satellite imagery (no search ran)",
    "error": "scene search failed",
    "searching": "scene search still running",
}


def imagery_result(entry: dict) -> str:
    """The map's result for one capture, e.g. "9 scenes, 2026-11-08 to
    2026-11-12" or "no scenes found under the cloud limit in the window"."""
    status = entry.get("status")
    if status in _STATUS_TEXT:
        return _STATUS_TEXT[status]
    count = entry.get("item_count")
    if count is None:
        return "shown"
    text = f"{count} scene{'' if count == 1 else 's'}"
    start, end = entry.get("start_date"), entry.get("end_date")
    if start and end:
        text += f", {start}" if start == end else f", {start} to {end}"
    return text


def describe_imagery(entry: dict) -> str:
    """One capture on the map, e.g. "sentinel-2 around 2026-11-10 (Jaru;
    ±7 days, <20% cloud): 9 scenes, 2026-11-08 to 2026-11-12"."""
    provider = entry.get("provider") or "sentinel-2"
    params = []
    areas = ", ".join(entry.get("aoi_names") or [])
    if areas:
        params.append(areas)
    if entry.get("window_days") is not None:
        params.append(f"±{entry['window_days']} days")
    if entry.get("max_cloud_cover") is not None:
        params.append(f"<{entry['max_cloud_cover']}% cloud")
    text = f"{provider} around {entry.get('target_date') or '?'}"
    if params:
        text += f" ({'; '.join(params)})"
    return f"{text}: {imagery_result(entry)}"


def find_imagery(
    view: Optional[dict], imagery_id: Optional[str]
) -> Optional[dict]:
    """The view-context entry for one capture, by its id (the recipe token)."""
    if not view or not imagery_id:
        return None
    for entry in view.get("visible_imagery") or []:
        if isinstance(entry, dict) and entry.get("imagery_id") == imagery_id:
            return entry
    return None
