"""AOI candidates found by the analytics API's area search, shaped like the
rows of Zeno's own database search so the geocoder can use either."""

from typing import Any, Optional

import httpx
import pandas as pd

from src.agent.datasets.handlers.analytics_handler import analytics_api_headers
from src.agent.subagents.pick_aoi.types import AreaOfInterestType

# The longest search text the API accepts.
MAX_QUERY_CHARS = 100


class AnalyticsApiAoiSearch:
    """Finds AOIs by name with `GET /v0/aois/search`, best match first."""

    def __init__(
        self,
        base_url: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def candidates(
        self,
        place_name: str,
        aoi_type: Optional[AreaOfInterestType],
        limit: int,
    ) -> pd.DataFrame:
        async with httpx.AsyncClient(transport=self.transport) as client:
            response = await client.get(
                f"{self.base_url}/v0/aois/search",
                params=search_params(place_name, aoi_type, limit),
                headers=analytics_api_headers(),
            )
            response.raise_for_status()
        matches = response.json()["data"]
        rows = [
            candidate_row(each)
            for each in matches
            if each["aoi_id"] != "global"
        ]
        return ranked(pd.DataFrame(rows))


def search_params(
    place_name: str, aoi_type: Optional[AreaOfInterestType], limit: int
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": place_name.replace("\x00", "")[:MAX_QUERY_CHARS],
        "limit": limit,
    }
    if aoi_type is not None:
        params["type"] = API_TYPES[aoi_type]
    return params


# The API's area type for each kind of area the geocoder can be asked for.
API_TYPES = {
    AreaOfInterestType.GADM: "admin",
    AreaOfInterestType.WDPA: "protected_area",
    AreaOfInterestType.KBA: "key_biodiversity_area",
    AreaOfInterestType.LANDMARK: "indigenous_land",
}

# Zeno's source and subtype for each non-admin API area type.
NAMED_AREA_KINDS = {
    "key_biodiversity_area": ("kba", "key-biodiversity-area"),
    "protected_area": ("wdpa", "protected-area"),
    "indigenous_land": ("landmark", "indigenous-and-community-land"),
    "custom_aoi": ("custom", "custom-area"),
}

# GADM subtypes by the number of levels below the country in an admin id.
ADMIN_SUBTYPES = (
    "country",
    "state-province",
    "district-county",
    "municipality",
    "locality",
    "neighbourhood",
)


def candidate_row(match: dict[str, Any]) -> dict[str, Any]:
    source, subtype, src_id = zeno_area(match["aoi_type"], match["aoi_id"])
    return {
        "source": source,
        "src_id": src_id,
        "name": match["display_name"],
        "leaf": match["name"],
        "subtype": subtype,
        "bbox": match.get("bbox"),
    }


def zeno_area(aoi_type: str, aoi_id: str) -> tuple[str, str, str]:
    """Zeno's source, subtype and id for an API area. Subnational GADM ids
    carry the version suffix Zeno stores, such as BRA.12_1 for BRA.12."""
    if aoi_type != "admin":
        source, subtype = NAMED_AREA_KINDS[aoi_type]
        return source, subtype, aoi_id
    depth = aoi_id.count(".")
    src_id = f"{aoi_id}_1" if depth else aoi_id
    return "gadm", ADMIN_SUBTYPES[depth], src_id


def ranked(rows: pd.DataFrame) -> pd.DataFrame:
    """The API returns the best match first; the geocoder sorts and merges by
    `similarity_score`, so rank becomes a score that falls with position."""
    if rows.empty:
        return rows
    return rows.assign(
        similarity_score=[1.0 / (rank + 1) for rank in range(len(rows))]
    )
