from typing import Any

from src.shared.geocoding_helpers import AOI_SOURCE_ID_COLUMNS

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


def admin_area(aoi_id: str) -> tuple[str, str, str]:
    depth = aoi_id.count(".")
    if depth >= len(ADMIN_SUBTYPES):
        raise UnsupportedAreaError(
            f"Admin areas below level 2 are not supported: {aoi_id}"
        )
    src_id = aoi_id if depth == 0 else f"{aoi_id}_1"
    return "gadm", ADMIN_SUBTYPES[depth], src_id
