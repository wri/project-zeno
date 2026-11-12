"""Analytics API areas as entries of Zeno's AOI selection, the shape the
frontend draws and the insight generator reads."""

import json
from typing import Any, Iterable

from langchain_core.messages import BaseMessage, ToolMessage

from src.shared.geocoding_helpers import AOI_SOURCE_ID_COLUMNS, format_id

# The AOI source and subtype that Zeno uses for each analytics API area type.
NAMED_AREA_KINDS = {
    "key_biodiversity_area": ("kba", "key-biodiversity-area"),
    "protected_area": ("wdpa", "protected-area"),
    "indigenous_land": ("landmark", "indigenous-and-community-land"),
}
# GADM subtypes by the number of levels below the country in an admin id.
ADMIN_SUBTYPES = ("country", "state-province", "district-county")


class UnsupportedAreaError(ValueError):
    pass


def area_selection_entry(match: dict[str, Any]) -> dict[str, Any]:
    """An area found by the analytics API, as an entry of Zeno's AOI
    selection. Subnational GADM ids carry the version suffix Zeno stores,
    such as BRA.14_1 for the API's BRA.14."""
    aoi_type = match["aoi"]["type"]
    aoi_id = match["aoi"]["ids"][0]
    if aoi_type == "admin":
        source, subtype, src_id = admin_area(aoi_id)
    elif aoi_type in NAMED_AREA_KINDS:
        source, subtype = NAMED_AREA_KINDS[aoi_type]
        src_id = aoi_id
    else:
        raise UnsupportedAreaError(
            f"Areas of type {aoi_type} are not supported"
        )
    return {
        "source": source,
        "src_id": src_id,
        AOI_SOURCE_ID_COLUMNS[source]: src_id,
        "name": match["display_name"],
        "subtype": subtype,
    }


def analyzed_areas(
    aoi: dict[str, Any],
    aoi_selection: dict[str, Any],
    names: dict[str, str],
) -> list[dict[str, Any]]:
    """The areas an analysis covered, as AOI selection entries: as selected
    when the selection holds them, otherwise named from `names` or by id."""
    selected = {
        format_id(area["src_id"]): area
        for area in aoi_selection.get("aois", [])
    }
    areas = []
    for aoi_id in aoi["ids"]:
        if aoi_id in selected:
            areas.append(selected[aoi_id])
            continue
        match = {
            "display_name": names.get(aoi_id, aoi_id),
            "aoi": {**aoi, "ids": [aoi_id]},
        }
        areas.append(area_selection_entry(match))
    return areas


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


def admin_area(aoi_id: str) -> tuple[str, str, str]:
    depth = aoi_id.count(".")
    if depth >= len(ADMIN_SUBTYPES):
        raise UnsupportedAreaError(
            f"Admin areas below level 2 are not supported: {aoi_id}"
        )
    src_id = aoi_id if depth == 0 else f"{aoi_id}_1"
    return "gadm", ADMIN_SUBTYPES[depth], src_id


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
