"""The kinds of area the geocoder can be asked for, and their sources.

These values reach the model twice: as the `area_of_interest` parameter of the
`pick_aoi` tool, and as the `area_type` a place is extracted with
(GEOCODER_PROMPT builds its list from this enum). They live here rather than
in tool.py so the prompt can import them without importing the tool.
"""

from enum import StrEnum
from typing import Optional, Protocol

import pandas as pd


class AreaOfInterestType(StrEnum):
    GADM = "administrative area (country, state/region, country/subregion)"
    WDPA = ("protected area, park, or reserve",)
    LANDMARK = ("indigenous region or territory",)
    KBA = "key biodiversity area"


aoi_to_table = {
    AreaOfInterestType.GADM: "gadm",
    AreaOfInterestType.WDPA: "wdpa",
    AreaOfInterestType.LANDMARK: "landmark",
    AreaOfInterestType.KBA: "kba",
}


class AoiCandidateSearch(Protocol):
    """Finds the AOIs whose names match a place, as rows with at least the
    columns ``source, src_id, name, subtype, bbox, similarity_score``."""

    async def candidates(
        self,
        place_name: str,
        aoi_type: Optional[AreaOfInterestType],
        limit: int,
    ) -> pd.DataFrame: ...
