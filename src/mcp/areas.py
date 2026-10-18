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

from src.agent.datasets.pull_checks import SUBREGION_LIMIT_ADMIN
from src.agent.subagents.pick_aoi.tool import (
    ExtractedPlace,
    Geocoder,
    PlaceQuery,
    SubregionType,
)
from src.agent.tools.send_nudge import NUDGE_ALREADY_SET_NOTE
from src.shared.aoi_search import (
    MAX_SEARCH_NAME_CHARS,
    SearchRequestError,
    search_aois,
)
from src.shared.database import get_connection_from_pool
from src.shared.gadm_admin_types import GadmAdminTerm
from src.shared.geocoding_helpers import VALID_AOI_SOURCES

# The sources a name search can match. Concessions have no search columns
# (they are reached as subregions), and custom areas need a user.
SearchSource = Literal["gadm", "kba", "wdpa", "landmark"]

MAX_SEARCH_RESULTS = 25
# The most areas one pull takes: the geocoder's limit for an administrative
# subregion expansion, so every selection resolve_areas returns can be pulled.
MAX_AREAS = SUBREGION_LIMIT_ADMIN
MAX_PLACES = 10


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


def _area_lines(found: list[dict]) -> str:
    return "\n".join(
        f"- {area['aoi_id']}: {area['name']} ({area['subtype']})"
        for area in found
    )


async def resolve_areas(
    places: Annotated[
        list[ExtractedPlace],
        Field(
            min_length=1,
            max_length=MAX_PLACES,
            description=(
                "One entry per distinct place the user names. For a "
                "worldwide question use the place 'World' with subregion "
                "'country'."
            ),
        ),
    ],
    subregion: Annotated[
        Optional[SubregionType],
        Field(description=PlaceQuery.model_fields["subregion"].description),
    ] = None,
    admin_term: Annotated[
        Optional[GadmAdminTerm],
        Field(description=PlaceQuery.model_fields["admin_term"].description),
    ] = None,
) -> ToolResult:
    """Resolve the places a user names to areas, the way Zeno's geocoder
    does, and expand them into their subregions when asked.

    Give each place as the user named it, in English, with its parent when
    the user gave one ('Para, Brazil'), plus the database spelling and other
    spellings when you know them. The tool picks the best area for each
    place, so use it rather than choosing from search_areas when the user
    names a place in plain words. Set subregion to compare the parts of a
    place ("the districts of Odisha", "protected areas in Peru").

    When a name is a prominent place in more than one country, it returns
    candidates and no selection: ask the user which one they mean, then use
    that candidate's aoi_id. Pass the returned aoi_ids to pull_data.
    """
    command = await Geocoder().lookup(
        question="; ".join(place.place for place in places),
        places=places,
        subregion=subregion,
        # The geocoder answers with LangChain ToolMessages, which need an id.
        tool_call_id="mcp",
        language="en",
        admin_term=admin_term,
        # The deterministic scorer, never a model pick.
        normalized=True,
    )
    update = command.update or {}
    messages = update.get("messages") or []
    message = str(messages[0].content) if messages else ""
    message = message.replace(NUDGE_ALREADY_SET_NOTE, "")

    selection = update.get("aoi_selection")
    if selection:
        found = [_area(aoi) for aoi in selection["aois"]]
        lines = [
            f"Selected {selection['name']}: {len(found)} area(s).",
            _area_lines(found),
        ]
        # The geocoder's own notes follow its list of names: places it could
        # not match, and the closest stored names for them.
        _, _, notes = message.partition("\n\n")
        if notes:
            lines.append(notes)
        return ToolResult(
            content="\n".join(lines),
            structured_content={
                "selection_name": selection["name"],
                "areas": found,
                "candidates": [],
            },
        )

    nudge = update.get("nudge") or {}
    if nudge.get("type") == "aoi_choice" and nudge.get("data"):
        candidates = [_area(aoi) for aoi in nudge["data"]]
        return ToolResult(
            content=(
                "The name matches places in more than one country, so "
                "nothing is selected. Ask the user which one they mean, "
                "then use its aoi_id:\n" + _area_lines(candidates)
            ),
            structured_content={
                "selection_name": None,
                "areas": [],
                "candidates": candidates,
            },
        )

    # No selection: the geocoder's reason (no match, too many subregions,
    # a worldwide question without subregion 'country').
    return ToolResult(
        content=message.strip() or "No area was selected.",
        structured_content={
            "selection_name": None,
            "areas": [],
            "candidates": [],
        },
    )
