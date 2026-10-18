"""Area tools: find areas by name, and read them back by id.

An area id is `<source>:<src_id>`, e.g. `gadm:BRA.14_1` — the same pair the
REST API's `AreaOfInterest` and the agent's `aoi_selection` carry, in one
string a model can copy. Custom areas belong to a user, and this server has
no user, so a `custom:` id is refused before it reaches a query.
"""

from typing import Annotated, Literal, Optional

from fastmcp.exceptions import ToolError
from fastmcp.tools.base import ToolResult
from pydantic import Field
from sqlalchemy import text

from src.shared.aoi_search import (
    MAX_SEARCH_NAME_CHARS,
    SearchRequestError,
    search_aois,
)
from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import VALID_AOI_SOURCES

# The sources a name search can match. Concessions have no search columns
# (they are reached as subregions), and custom areas need a user.
SearchSource = Literal["gadm", "kba", "wdpa", "landmark"]

MAX_SEARCH_RESULTS = 25


def format_aoi_id(source: str, src_id: str) -> str:
    return f"{source}:{src_id}"


def parse_aoi_id(aoi_id: str) -> tuple[str, str]:
    """`(source, src_id)` of an area id; raises ToolError when malformed,
    unknown, or a custom area."""
    source, sep, src_id = aoi_id.strip().partition(":")
    if not sep or not source or not src_id:
        raise ToolError(
            f"'{aoi_id}' is not an area id. Area ids look like "
            "'gadm:BRA.14_1'; get them from search_areas."
        )
    if source == "custom":
        raise ToolError(
            "Custom areas are not available on this server. Use an area "
            "from search_areas."
        )
    if source not in VALID_AOI_SOURCES:
        raise ToolError(
            f"'{aoi_id}' has an unknown source '{source}'. Get area ids "
            "from search_areas."
        )
    return source, src_id


def _bbox(value) -> Optional[list[float]]:
    return [float(v) for v in value] if value is not None else None


def _area(row: dict) -> dict:
    return {
        "aoi_id": format_aoi_id(row["source"], str(row["src_id"])),
        "name": row["name"],
        "subtype": row["subtype"],
        "source": row["source"],
        "bbox": _bbox(row.get("bbox")),
    }


async def lookup_areas(aoi_ids: list[str]) -> list[dict]:
    """The areas behind `aoi_ids`, in the order given, in the shape the
    analytics handler takes (`source`, `src_id`, `name`, `subtype`, `bbox`).

    Raises ToolError naming every id that has no live area, so a model that
    invented or mistyped one learns which and where to get a real one.
    """
    pairs = [parse_aoi_id(aoi_id) for aoi_id in aoi_ids]
    query = text(
        "SELECT source, source_id AS src_id, name, subtype, bbox "
        "FROM aois "
        "WHERE NOT is_deprecated AND source <> 'custom' "
        "AND (source, source_id) IN ("
        "  SELECT * FROM unnest(CAST(:sources AS text[]), CAST(:ids AS text[]))"
        ")"
    )
    async with get_connection_from_pool() as conn:
        result = await conn.execute(
            query,
            {
                "sources": [source for source, _ in pairs],
                "ids": [src_id for _, src_id in pairs],
            },
        )
        rows = {
            (row["source"], row["src_id"]): row
            for row in result.mappings().all()
        }
    missing = [
        aoi_id for aoi_id, pair in zip(aoi_ids, pairs) if pair not in rows
    ]
    if missing:
        raise ToolError(
            f"No area found for {', '.join(missing)}. Get area ids from "
            "search_areas; do not write them from memory."
        )
    return [
        {
            "source": source,
            "src_id": src_id,
            "name": rows[(source, src_id)]["name"],
            "subtype": rows[(source, src_id)]["subtype"],
            "bbox": _bbox(rows[(source, src_id)]["bbox"]),
        }
        for source, src_id in pairs
    ]


async def search_areas(
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_SEARCH_NAME_CHARS,
            description=(
                "The place name, in English, as 'Place' or 'Place, Parent' "
                "(e.g. 'Para, Brazil', 'Odisha', 'Yasuni National Park')."
            ),
        ),
    ],
    sources: Annotated[
        Optional[list[SearchSource]],
        Field(
            description=(
                "Limit the search to these sources: gadm (countries and "
                "administrative units), kba (key biodiversity areas), wdpa "
                "(protected areas), landmark (indigenous and community "
                "lands). Omit to search all of them."
            )
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=MAX_SEARCH_RESULTS)] = 10,
) -> ToolResult:
    """Find areas (countries, states, districts, protected areas, key
    biodiversity areas, indigenous lands) by name.

    Returns the best matches first, each with the `aoi_id` that pull_data
    takes. Pick the area the user means from the results; when more than one
    fits (the same name in two countries), ask the user. A result marked
    "spelling corrected" is a guess: confirm it before using it.
    """
    try:
        df = await search_aois(
            name=name,
            sources=list(sources) if sources else None,
            user_id=None,
            limit=limit,
            include_custom=False,
        )
    except SearchRequestError as exc:
        raise ToolError(str(exc)) from exc

    rows = df.to_dict(orient="records")
    areas = []
    lines = []
    for row in rows:
        area = _area(row)
        area["corrected"] = bool(row.get("corrected", False))
        areas.append(area)
        guess = " — spelling corrected, confirm" if area["corrected"] else ""
        lines.append(
            f"- {area['aoi_id']}: {area['name']} ({area['subtype']}){guess}"
        )
    if not areas:
        message = (
            f"No area matches '{name}'. Try a broader name (the country or "
            "region) or another spelling."
        )
    else:
        message = f"Areas matching '{name}', best first:\n" + "\n".join(lines)
    return ToolResult(content=message, structured_content={"areas": areas})
