import json
from typing import Any, Iterable

from langchain_core.messages import BaseMessage, ToolMessage


def names_seen(messages: Iterable[BaseMessage]) -> dict[str, str]:
    """Area names by aoi id, from the areas earlier tool results listed: the
    selected areas and other matches of pick_aoi, and the areas of
    list_subregions."""
    names: dict[str, str] = {}
    for message in messages:
        if isinstance(message, ToolMessage):
            for area in listed_areas(message.content):
                for aoi_id in area["aoi"]["ids"]:
                    names[aoi_id] = area["name"]
    return names


def listed_areas(content: Any) -> list[dict[str, Any]]:
    """The named areas in a tool result, or none when it lists no areas."""
    try:
        result = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError:
        return []
    if not isinstance(result, dict):
        return []
    areas = list(result.get("areas") or [])
    areas.extend(result.get("selected") or [])
    for matches in (result.get("other_matches") or {}).values():
        areas.extend(matches)
    return [area for area in areas if is_named_area(area)]


def is_named_area(area: Any) -> bool:
    return (
        isinstance(area, dict)
        and isinstance(area.get("name"), str)
        and isinstance((area.get("aoi") or {}).get("ids"), list)
    )
