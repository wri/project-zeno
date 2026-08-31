"""The kinds of area the geocoder can be asked for, and their sources.

These values reach the model twice: as the `area_of_interest` parameter of the
`pick_aoi` tool, and as the `area_type` a place is extracted with
(GEOCODER_PROMPT builds its list from this enum). They live here rather than
in tool.py so the prompt can import them without importing the tool.
"""

from enum import StrEnum


class AreaOfInterestType(StrEnum):
    GADM = "adminstrative area (country, state/region, country/subregion)"
    WDPA = ("protected area, park, or reserve",)
    LANDMARK = ("indigenous region or territory",)
    KBA = "key biodiversity area"


aoi_to_table = {
    AreaOfInterestType.GADM: "gadm",
    AreaOfInterestType.WDPA: "wdpa",
    AreaOfInterestType.LANDMARK: "landmark",
    AreaOfInterestType.KBA: "kba",
}
