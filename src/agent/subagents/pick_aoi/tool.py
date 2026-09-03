import asyncio
from typing import (
    Annotated,
    Any,
    Dict,
    Literal,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
)

import pandas as pd
from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from src.agent.config import AgentSettings
from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.llms import SMALL_MODEL
from src.agent.subagents.pick_aoi.global_queries import (
    handle_global_request,
    is_global_request,
)
from src.agent.subagents.pick_aoi.prompts import GEOCODER_PROMPT
from src.agent.subagents.pick_aoi.scoring import best_candidate_row
from src.agent.subagents.pick_aoi.selection_name_util import (
    build_selection_name,
)
from src.agent.subagents.pick_aoi.types import (
    AreaOfInterestType,
    aoi_to_table,
)
from src.agent.subagents.progress import emit_progress
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.send_nudge import NUDGE_ALREADY_SET_NOTE
from src.shared.database import get_connection_from_pool
from src.shared.gadm_admin_types import GadmAdminTerm, resolve_gadm_admin_level
from src.shared.geocoding_helpers import (
    AOI_SOURCE_ID_COLUMNS,
    SUBREGION_TO_SUBTYPE_MAPPING,
    search_aois,
)
from src.shared.logging_config import get_logger
from src.shared.request_context import current_user_id

RESULT_LIMIT = 10
SUBREGION_LIMIT_ADMIN = 1000
SUBREGION_LIMIT = 50

load_dotenv()
logger = get_logger(__name__)


class AOIId(BaseModel):
    src_id: str = Field(description="`src_id` of the best matched location.")


class AOIIndex(BaseModel):
    """Model for storing the best matched location."""

    model_config = ConfigDict(extra="allow")

    source: str = Field(description="`source` of the best matched location.")
    src_id: str = Field(description="`src_id` of the best matched location.")
    name: str = Field(description="`name` of the best matched location.")
    subtype: str = Field(description="`subtype` of the best matched location.")
    bbox: list[float] = Field(
        description="Bounding box of the best matched location as [minx, miny, maxx, maxy].",
        default=[-180.0, -90.0, 180.0, 90.0],
    )


async def query_aoi_database(
    place_name: str,
    aoi_type: Optional[AreaOfInterestType],
    result_limit: int = 10,
):
    """Find the AOIs whose name matches *place_name*.

    This delegates to ``search_aois``, which is the same search core that
    ``GET /api/aois`` uses. Both therefore rank candidates the same way.

    Args:
        place_name: Name of the place to search for
        aoi_type: One source to restrict the search to, or None for all
        result_limit: Maximum number of results to return

    Returns:
        DataFrame with the columns ``src_id, name, subtype, source, bbox,
        similarity_score``. Disputed and deprecated AOIs are excluded.
    """
    sources = [aoi_to_table[aoi_type]] if aoi_type is not None else None
    user_id = current_user_id()
    return await search_aois(
        name=place_name,
        sources=sources,
        user_id=user_id,
        limit=result_limit,
        offset=0,
    )


async def query_aoi_database_multiterm(
    search_terms: list[str],
    aoi_type: Optional[AreaOfInterestType],
    result_limit: int = RESULT_LIMIT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Find the AOIs matching any of *search_terms*, merged.

    Each term gets its own query with its own ``result_limit``, so a
    low-similarity alias ("Zaire" for "DR Congo") is not crowded out of a
    shared limit by the main spelling. A row that several terms match is
    deduplicated on ``(source, src_id)``, keeping its highest
    ``similarity_score``.

    ``query_aoi_database`` stays single-term deliberately: the replay
    fixtures and the agent tests patch it once per term.

    Args:
        search_terms: Terms to search, the extracted place name first.
        aoi_type: One source to restrict every search to, or None for all.
        result_limit: Maximum number of results per term.

    Returns:
        ``(merged, primary)``, where ``primary`` is the first term's own
        result frame. It is returned separately because the ambiguity check
        may only consider rows that the place name itself retrieved: an
        ``aoi_choice`` option is resubmitted as the next question, so
        offering a choice over rows found by an invented alias would re-offer
        the same choice forever (see ``check_duplicate_aois`` and
        ``_format_aoi_candidate``).

    Raises:
        ValueError: If ``search_terms`` is empty.
    """
    if not search_terms:
        raise ValueError("query_aoi_database_multiterm needs a search term")

    frames = await asyncio.gather(
        *[
            query_aoi_database(term, aoi_type, result_limit)
            for term in search_terms
        ]
    )
    primary = frames[0]
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        # An empty frame is what makes the caller report the place as
        # unmatched, so preserve it rather than inventing columns.
        return primary, primary

    combined = pd.concat(populated, ignore_index=True)
    # This sort is what decides WHICH copy of a row `drop_duplicates` keeps
    # below: the highest-scoring one. Stable, so rows tied on score keep term
    # order and the merge is deterministic for identical inputs.
    combined = combined.sort_values(
        "similarity_score", ascending=False, kind="stable"
    )
    merged = combined.drop_duplicates(
        subset=["source", "src_id"], keep="first"
    ).reset_index(drop=True)
    return merged, primary


# The AOI source that each subregion scope resolves to. GADM holds all six admin
# scopes. Each other scope names its own source.
SUBREGION_SOURCE_MAPPING = {
    "country": "gadm",
    "state": "gadm",
    "district": "gadm",
    "municipality": "gadm",
    "locality": "gadm",
    "neighbourhood": "gadm",
    "kba": "kba",
    "wdpa": "wdpa",
    "landmark": "landmark",
}


async def query_subregion_database(
    subregion_name: str, source: str, src_id: str
):
    """Find the subregions of a selected AOI. Both come from the unified table.

    Args:
        subregion_name: Scope to expand into (an admin level, or kba/wdpa/landmark)
        source: Source of the selected (parent) AOI
        src_id: id of the selected AOI within its source

    Returns:
        DataFrame of subregions, with the columns ``name, subtype, <source id
        column>, source, src_id, bbox``. The source-specific id column
        (``gadm_id``, ``sitrecid``, ...) repeats ``src_id``. It remains because
        the frontend reads it from the extra fields of ``AOIIndex``.

    A GADM parent selects its children by an id prefix. Any other source
    selects them by a spatial overlap. A non-GADM parent with an admin
    subregion gets no containment filter at all, so the result holds every
    admin unit of that subtype worldwide. ``check_aoi_selection`` then rejects
    it as too many subregions. This is a known defect.
    """
    if subregion_name not in SUBREGION_SOURCE_MAPPING:
        logger.error(f"Invalid subregion: {subregion_name}")
        raise ValueError(
            f"Subregion: {subregion_name} does not match to any table in PostGIS database."
        )

    subregion_source = SUBREGION_SOURCE_MAPPING[subregion_name]
    subtype = SUBREGION_TO_SUBTYPE_MAPPING[subregion_name]
    src_id_field = AOI_SOURCE_ID_COLUMNS[subregion_source]

    logger.info(
        f"Querying subregion: {subregion_name} in source: {subregion_source} "
        f"for source: {source}, src_id: {src_id}"
    )

    params: Dict[str, Any] = {
        "src_id": src_id,
        "source": source,
        "subregion_source": subregion_source,
        "subtype": subtype,
    }

    if subregion_source == "gadm":
        # The GADM id holds the hierarchy, so a prefix match gives containment.
        # A spatial test is not necessary.
        if source == "gadm":
            # Match the children of this admin id, one level down. The `_1` or
            # `_2` version suffix is not part of the hierarchy, so the code
            # removes it first. The prefix therefore cannot hold the `_`
            # wildcard of LIKE.
            params["gadm_prefix"] = f"{src_id.split('_')[0]}.%"
            gadm_filter = "AND t.source_id LIKE :gadm_prefix"
        else:
            # A non-GADM parent gets no containment filter, only the exclusion of
            # disputed territories. The query then returns every admin unit of
            # the subtype worldwide, and check_aoi_selection rejects the result
            # as too many subregions. This is a known defect.
            gadm_filter = "AND NOT t.is_disputed"
        spatial_filter = ""
    else:
        gadm_filter = ""
        # Accept an overlap, but reject a shared border alone. The parent
        # geometry is a normalized MultiPolygon, so a repaired boundary can give
        # a slightly different result than the raw source geometry.
        spatial_filter = (
            "AND ST_Intersects(t.geometry, parent.geom) "
            "AND NOT ST_Touches(t.geometry, parent.geom)"
        )

    # `bbox` is computed at build time. COALESCE replaces a null array with the
    # world bbox, which is the default of AOIIndex.
    sql_query = f"""
    WITH parent AS (
        SELECT geometry AS geom
        FROM aois
        WHERE source = :source
          AND source_id = :src_id
          AND NOT is_deprecated
        LIMIT 1
    )
    SELECT
        t.name,
        t.subtype,
        t.source_id AS {src_id_field},
        t.source AS source,
        t.source_id AS src_id,
        COALESCE(
            t.bbox, ARRAY[-180, -90, 180, 90]::double precision[]
        ) AS bbox
    FROM aois AS t, parent
    WHERE t.source = :subregion_source
      AND t.subtype = :subtype
      AND NOT t.is_deprecated
      {gadm_filter}
      {spatial_filter}
    """
    logger.debug(f"Executing subregion query: {sql_query}")

    async with get_connection_from_pool() as conn:

        def _read(sync_conn):
            return pd.read_sql(text(sql_query), sync_conn, params=params)

        results = await conn.run_sync(_read)

    return results


def score_best_aoi(
    candidate_aois: pd.DataFrame, terms: Sequence[str]
) -> Optional[AOIIndex]:
    """Pick the best candidate deterministically, with no model call.

    The scoring itself lives in `scoring.py`; this only turns the winning row
    into the model the rest of the tool passes around. No score comes back
    with it: AOIIndex allows extra fields, so a score written onto the row
    would leak into aoi_selection.
    """
    best_row = best_candidate_row(candidate_aois, terms)
    if best_row is None:
        return None
    return AOIIndex(**best_row)


async def select_best_aoi(
    question: str, candidate_aois: pd.DataFrame
) -> Optional[AOIIndex]:
    """Select the best AOI based on the user query.

    Args:
        question: User's question providing context for selecting the most relevant location
        candidate_aois: Candidate AOIs to select from

    Returns:
        Selected AOI: AOIIndex, or None if no candidates or no match found
    """
    if candidate_aois.empty:
        logger.debug("No candidate AOIs to select from")
        return None

    # Prompt template for selecting the best location match based on user query
    AOI_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """
                From the candidate locations below, select the one place that best matches the user's query intention for location.
                Consider the context and purpose mentioned in the user query to determine the most appropriate geographic scope.

                When there is a tie, give preference to country > state > district > municipality > locality.

                Candidate locations:
                {candidate_aois_csv}

                User query:
                {user_query}
                """,
            )
        ]
    )

    # Chain for selecting the best location match and returning the src_id.
    # run_name is what this call is labelled in Langfuse, and so what
    # derived.cost_by_component attributes its spend to.
    AOI_SELECTION_CHAIN = (
        AOI_SELECTION_PROMPT | SMALL_MODEL.with_structured_output(AOIId)
    ).with_config(run_name="select_aoi")

    selected_aoi_index = await AOI_SELECTION_CHAIN.ainvoke(
        {
            "candidate_aois_csv": candidate_aois.to_csv(index=False),
            "user_query": question,
        }
    )
    # Get the original data row for the selected AOI
    matched = candidate_aois[
        candidate_aois["src_id"] == selected_aoi_index.src_id
    ]
    if matched.empty:
        logger.warning(
            f"LLM selected src_id '{selected_aoi_index.src_id}' "
            f"not found in candidates. Available: {list(candidate_aois['src_id'])}"
        )
        return None
    selected_aoi_row = matched.iloc[0]
    selected_aoi = AOIIndex(**selected_aoi_row.to_dict())

    logger.debug(f"Candidate AOIs: {candidate_aois}")
    logger.debug(f"Selected AOI: {selected_aoi}")

    return selected_aoi


async def check_multiple_matches(
    src_id: str, short_name: str, results: pd.DataFrame
) -> Optional[list[dict]]:
    # A place can now be resolved by a canonical name or an alternative
    # spelling while the place name itself matched nothing, so this can be
    # reached with an empty frame and a valid selection — a state that was
    # impossible when an empty frame always meant no selection.
    if results.empty:
        return None

    # Extract country code from selected AOI's src_id (e.g., "IND.12.26_1" -> "IND")
    selected_country = src_id.split(".")[0] if "." in src_id else None

    if selected_country:
        # Filter results to only include AOIs from different countries
        different_country_results = results[
            (results.source == "gadm")
            & (~results.src_id.str.startswith(selected_country + "."))
        ]

        # Find exact matches of the short name in different countries
        exact_matches_different_countries = different_country_results[
            different_country_results.name.str.lower().str.startswith(
                short_name.lower()
            )
        ]

        # If we have exact matches from different countries, ask for clarification
        if len(exact_matches_different_countries) > 0:
            # Include the selected AOI and the matches from other countries
            all_matches = results[
                (results.name.str.lower().str.startswith(short_name.lower()))
                & (results.source == "gadm")
            ]

            # Same columns as AOIIndex, so these candidates match the shape
            # of an already-picked aoi_selection entry.
            return all_matches[
                ["source", "src_id", "name", "subtype", "bbox"]
            ].to_dict(orient="records")

    return None


def _format_aoi_candidate(candidate: dict) -> str:
    """Render one aoi_choice option.

    The leading `name` must stay the full comma-joined hierarchy
    ("Paris, Île-de-France, France"), not the bare leaf: clicking an option
    resubmits this string, and pick_aoi re-resolves it by trigram similarity
    against the same `name` column (see search_aois). The full hierarchy
    matches only the intended row; a bare "Paris" would re-match every Paris
    and re-offer the same choice indefinitely.
    """
    return (
        f"{candidate['name']} - ({candidate['subtype']}) "
        f"[{candidate['src_id'].split('.')[0]}]"
    )


async def check_aoi_selection(
    aois: list[AOIIndex], language: str = DEFAULT_LANGUAGE
) -> Optional[str]:
    if not aois:
        return await t("pick_aoi.no_matching_aois", language)

    aoi_sources = set([aoi.source for aoi in aois])
    if len(aoi_sources) > 1:
        return await t("pick_aoi.multiple_sources", language)

    aoi_source = next(iter(aoi_sources))
    if aoi_source in {"kba", "wdpa", "landmark"}:
        subregion_limit = SUBREGION_LIMIT
    else:
        subregion_limit = SUBREGION_LIMIT_ADMIN

    if len(aois) > subregion_limit:
        return await t(
            "pick_aoi.too_many_subregions",
            language,
            count=len(aois),
            subregion_limit=SUBREGION_LIMIT,
            subregion_limit_admin=SUBREGION_LIMIT_ADMIN,
        )

    return None


async def check_duplicate_aois(
    selected_aois: list[AOIIndex],
    all_results: list[pd.DataFrame],
    language: str = DEFAULT_LANGUAGE,
) -> Optional[tuple[str, list[str], list[dict]]]:
    """Returns (message, options, data) when the same place name matches
    AOIs in different countries — ``options`` are the exact candidate
    strings for the ``aoi_choice`` nudge (clicking one resubmits it as the
    next question); ``data`` are the same candidates as AOIIndex-shaped
    dicts, matching the aoi_selection.aois entries a pick would produce."""
    for selected_aoi, result in zip(selected_aois, all_results):
        if selected_aoi.source == "gadm":
            short_name = selected_aoi.name.split(",")[0]
            candidates = await check_multiple_matches(
                selected_aoi.src_id, short_name, result
            )
            if candidates:
                options = [_format_aoi_candidate(c) for c in candidates]
                message = await t(
                    "pick_aoi.duplicate_names",
                    language,
                    short_name=short_name,
                    candidate_names="\n".join(options),
                )
                return message, options, candidates

    return None


SubregionType = Literal[
    "country",
    "state",
    "district",
    "municipality",
    "locality",
    "neighbourhood",
    "kba",
    "wdpa",
    "landmark",
]


# Admin subregion depth -> generic SubregionType label, used to translate a
# country-resolved GADM level (from resolve_gadm_admin_level) back into the
# vocabulary query_subregion_database expects.
LEVEL_TO_SUBREGION: Dict[int, str] = {
    1: "state",
    2: "district",
    3: "municipality",
    4: "locality",
    5: "neighbourhood",
}


def _resolve_effective_subregion(
    subregion: str, admin_term: Optional[str], selected_aoi: AOIIndex
) -> Tuple[str, bool]:
    """Override *subregion* with the country-correct GADM depth, if resolvable.

    The LLM extracts one subregion depth per request, but the correct depth
    for a given admin term is country-specific (Spain's "provinces" are one
    level deeper than Canada's). This resolves it per selected AOI instead,
    which also makes a multi-country request (e.g. "provinces of Spain and
    Canada") resolve correctly for each place independently. Falls back to
    the LLM's original guess when there's no admin_term, the parent isn't a
    GADM place, or the term doesn't resolve for that country.

    Returns the effective subregion together with whether *admin_term* is
    what actually produced it -- the caller uses this to decide whether it's
    safe to display the user's own word instead of the generic subregion
    label (it isn't, when the term didn't resolve for this AOI's country).
    """
    if not admin_term or selected_aoi.source != "gadm":
        return subregion, False
    if subregion not in LEVEL_TO_SUBREGION.values():
        return subregion, False
    iso3 = selected_aoi.src_id.split(".")[0]
    level = resolve_gadm_admin_level(admin_term, iso3)
    if level is None:
        return subregion, False
    return LEVEL_TO_SUBREGION[level], True


class ExtractedPlace(BaseModel):
    """One place the geocoder extracted, normalised for our tables.

    `place` keeps exactly the semantics it had when `PlaceQuery.places` was a
    list of strings: English, de-accented, parent kept in the same string. It
    is always searched, which makes every other field additive — a poor
    canonical name or a wrong alternative can only add candidates, never take
    away the one the place name itself would have found.
    """

    place: str = Field(
        description=(
            "English place name as the user gave it. A place and its parent "
            "stay in one string, e.g. 'Lisbon, Portugal'."
        ),
    )
    canonical: str = Field(
        default="",
        description=(
            "The place's own name as a geographic database stores it: "
            "official spelling with accents, acronyms and exonyms expanded, "
            "words describing the kind of area removed, parent kept."
        ),
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description=(
            "Up to 3 other spellings the database might store instead: the "
            "short form, a native-script name, a historical name."
        ),
    )
    area_type: Optional[AreaOfInterestType] = Field(
        default=None,
        description=(
            "The kind of area, when the request says which — this is where "
            "a designation such as 'National Park' belongs, rather than in "
            "the name. Null for a plain administrative place."
        ),
    )


class PlaceQuery(BaseModel):
    """A place request the geocoder extracts from the user's message."""

    places: list[ExtractedPlace] = Field(
        default_factory=list,
        description="One entry per distinct location.",
    )
    subregion: Optional[SubregionType] = Field(
        default=None,
        description=(
            "Set only to compare or analyze across many administrative units "
            "inside the place(s); otherwise leave null."
        ),
    )
    admin_term: Optional[GadmAdminTerm] = Field(
        default=None,
        description=(
            "Set together with an administrative subregion (state/district/"
            "municipality/locality/neighbourhood) to the exact local word the "
            "user used for that unit (e.g. 'province', 'canton', 'department'"
            ", 'constituent country'), normalized to this enum's closest "
            "member. Administrative terminology means a different depth in "
            "different countries (Spain's provinces are one level deeper "
            "than Canada's), so this resolves the correct depth per country "
            "instead of guessing one depth globally. Leave null for "
            "subregion=country/kba/wdpa/landmark, which are unambiguous."
        ),
    )


class _PlaceResolution(NamedTuple):
    """What one place resolved to: its plan, its candidates and its pick."""

    place: ExtractedPlace
    terms: list[str]
    merged: pd.DataFrame
    primary: pd.DataFrame
    selection: Optional[AOIIndex]


async def _resolve_place(
    place: ExtractedPlace,
    question: str,
    aoi_type: Optional[AreaOfInterestType],
    normalized: bool,
) -> _PlaceResolution:
    """Search one place and pick its AOI, planned once at the top.

    The plan is the whole of what the kill switch governs, which is why it is
    decided here rather than threaded through the steps below: with the
    normaliser off a place is searched under its extracted name alone, its
    inferred type is ignored, and a model picks the winner — exactly the
    pre-PZB-1272 behaviour.

    The extracted name always leads the term set and is always searched, so
    normalisation can only ADD candidates: it can never remove the row the
    place name alone would have found. Narrowing to a source carries weight
    now that a designation no longer travels in the search term (with the
    whole catalogue in scope, an admin unit sharing a park's leaf name
    outranks the park on the hierarchy term alone), but a wrong type must not
    cost recall — so an empty narrowed result is retried across every source.
    """
    terms = [place.place]
    # The caller's explicit `area_of_interest` wins; the type the geocoder
    # inferred for this place only fills the gap when the caller gave none.
    effective_type = aoi_type
    if normalized:
        for candidate in [place.canonical, *place.alternatives]:
            if candidate and candidate not in terms:
                terms.append(candidate)
        if effective_type is None:
            effective_type = place.area_type

    merged, primary = await query_aoi_database_multiterm(terms, effective_type)
    if merged.empty and normalized and effective_type is not None:
        logger.info(
            "GEOCODER: no %s candidates for %r; retrying every source",
            effective_type,
            place.place,
        )
        merged, primary = await query_aoi_database_multiterm(terms, None)

    if normalized:
        # No model chooses among candidates: identical candidates always
        # produce the identical AOI.
        selection = score_best_aoi(merged, terms)
    else:
        selection = await select_best_aoi(question, merged)
    return _PlaceResolution(place, terms, merged, primary, selection)


# Turns a free-text request into structured place(s) + subregion. The rules
# the LLM follows live in GEOCODER_PROMPT (prompts.py).
GEOCODER_EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [("system", GEOCODER_PROMPT), ("user", "{question}")]
)


class Geocoder:
    """Natural-language geocoder: resolves a place request to an AOI.

    Used as a tool by the orchestrator via `pick_aoi`. The orchestrator passes
    the user's request verbatim; this subagent does its own reasoning:

      1. `extract` — an LLM step that turns the request into English place
         name(s) and an optional subregion (GEOCODER_PROMPT holds the rules).
      2. `lookup` — looks each place up in the spatial database, picks the
         best candidate, expands subregions and validates the selection.

    All place / country / subregion logic lives behind this boundary, so the
    tool call itself stays trivial.
    """

    async def resolve(
        self,
        question: str,
        aoi_type: Optional[AreaOfInterestType],
        tool_call_id: Optional[str] = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> Command:
        """Full resolution: extract place(s) from the request, then look up."""
        query = await self.extract(question, aoi_type)
        logger.info(
            "GEOCODER: extracted places=%r subregion=%r",
            [place.model_dump() for place in query.places],
            query.subregion,
        )
        if not query.places:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            await t("pick_aoi.no_place", language),
                            tool_call_id=tool_call_id,
                            status="success",
                            response_metadata={"msg_type": "human_feedback"},
                        )
                    ],
                },
            )
        return await self.lookup(
            question,
            query.places,
            query.subregion,
            aoi_type,
            tool_call_id,
            language,
            query.admin_term,
        )

    async def extract(
        self, question: str, aoi_type: Optional[AreaOfInterestType]
    ) -> PlaceQuery:
        """LLM step: turn the user's request into place(s) + subregion."""
        chain = (
            GEOCODER_EXTRACTION_PROMPT
            | SMALL_MODEL.with_structured_output(PlaceQuery)
        ).with_config(run_name="extract_place_query")
        return await chain.ainvoke({"question": question})

    async def lookup(
        self,
        question: str,
        # Sequence, not list: `resolve` passes a list[ExtractedPlace] and
        # list is invariant.
        places: Sequence[ExtractedPlace],
        subregion: Optional[SubregionType] = None,
        aoi_type: Optional[AreaOfInterestType] = None,
        tool_call_id: Optional[str] = None,
        language: str = DEFAULT_LANGUAGE,
        admin_term: Optional[str] = None,
    ) -> Command:
        """DB step: resolve known place name(s) to AOI geometry."""
        place_names = [place.place for place in places]
        logger.info(
            f"GEOCODER: lookup places: '{place_names}', "
            f"subregion: '{subregion}'"
        )

        if is_global_request(place_names):
            logger.info("GEOCODER: global request detected")
            emit_progress("pick_aoi", "global", "Global (worldwide) request")
            return await handle_global_request(
                subregion, tool_call_id, language
            )

        normalized = AgentSettings.aoi_normalizer_enabled
        resolutions = await asyncio.gather(
            *[
                _resolve_place(place, question, aoi_type, normalized)
                for place in places
            ]
        )

        # Progress stays grouped by stage rather than interleaved per place,
        # so the reader sees one block per stage however many places there are.
        for resolution in resolutions:
            if len(resolution.terms) > 1:
                emit_progress(
                    "pick_aoi",
                    "normalize",
                    f"Searching '{resolution.place.place}' as: "
                    f"{'; '.join(resolution.terms)}",
                )
        for resolution in resolutions:
            result = resolution.merged
            count = len(result) if "name" in result.columns else 0
            # Only the names the message shows: the count comes from the frame.
            names = result["name"].head(8).tolist() if count else []
            emit_progress(
                "pick_aoi",
                "candidates",
                f"Fuzzy search '{resolution.place.place}': "
                f"{count} candidate(s)"
                + (f" — {'; '.join(names)}" if names else ""),
            )

        unmatched_places = [
            resolution.place.place
            for resolution in resolutions
            if resolution.selection is None
        ]
        # Each selection stays paired with the candidates of ITS OWN place:
        # filtering the selections alone would pair one with another place's
        # candidates as soon as a place matched nothing.
        matched = [
            (resolution.selection, resolution.primary)
            for resolution in resolutions
            if resolution.selection is not None
        ]
        selected_aois = [aoi for aoi, _ in matched]
        if not selected_aois:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            "No matching location was found for: "
                            f"{', '.join(unmatched_places)}. Try a broader "
                            "place name (e.g., the country or region) or "
                            "rephrase the location.",
                            tool_call_id=tool_call_id,
                            status="success",
                            response_metadata={"msg_type": "human_feedback"},
                        )
                    ],
                },
            )

        duplicate_check = await check_duplicate_aois(
            selected_aois,
            # Only the rows the place name itself retrieved. An aoi_choice
            # option is resubmitted verbatim as the next question, so
            # offering a choice over rows that only an invented alias found
            # would re-offer the same choice indefinitely.
            [primary for _, primary in matched],
            language,
        )
        if duplicate_check:
            message, options, data = duplicate_check
            return Command(
                update={
                    "nudge": {
                        "type": "aoi_choice",
                        "options": options,
                        "data": data,
                    },
                    "messages": [
                        ToolMessage(
                            message + NUDGE_ALREADY_SET_NOTE,
                            tool_call_id=tool_call_id,
                            status="success",
                            response_metadata={"msg_type": "human_feedback"},
                        )
                    ],
                },
            )

        match_names = [selected_aoi.name for selected_aoi in selected_aois]
        emit_progress(
            "pick_aoi", "matched", f"Picked: {', '.join(match_names)}"
        )

        admin_term_resolved = True
        if subregion:
            effective_subregions = []
            for selected_aoi in selected_aois:
                effective, resolved = _resolve_effective_subregion(
                    subregion, admin_term, selected_aoi
                )
                effective_subregions.append(effective)
                admin_term_resolved = admin_term_resolved and resolved
            subregion_tasks = [
                query_subregion_database(
                    effective, selected_aoi.source, selected_aoi.src_id
                )
                for effective, selected_aoi in zip(
                    effective_subregions, selected_aois
                )
            ]
            subregion_dfs = await asyncio.gather(*subregion_tasks)
            final_aois = []
            for df in subregion_dfs:
                final_aois.extend(
                    [AOIIndex(**row) for row in df.to_dict(orient="records")]
                )
            emit_progress(
                "pick_aoi",
                "subregion",
                f"Comparing across {len(final_aois)} {subregion} area(s)",
            )
        else:
            final_aois = selected_aois

        logger.info(f"Found {len(final_aois)} AOIs in total")

        check = await check_aoi_selection(final_aois, language)
        if check:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            check,
                            tool_call_id=tool_call_id,
                            status="success",
                            response_metadata={"msg_type": "human_feedback"},
                        )
                    ],
                },
            )

        tool_message = "Selected AOIs:"
        for selected_aoi in final_aois:
            tool_message += f"\n- {selected_aoi.name}"
        if unmatched_places:
            tool_message += (
                "\n\nNo match found for: "
                f"{', '.join(unmatched_places)}. These were skipped."
            )

        logger.debug(f"Pick AOI tool message: {tool_message}")

        selection_name = build_selection_name(
            match_names,
            subregion,
            len(final_aois),
            display_term=admin_term if admin_term_resolved else None,
        )

        logger.info(f"AOI selection name: {selection_name}")

        return Command(
            update={
                "aoi_selection": {
                    "name": selection_name,
                    "aois": [aoi.model_dump() for aoi in final_aois],
                },
                "messages": [
                    ToolMessage(tool_message, tool_call_id=tool_call_id)
                ],
            },
        )


@tool("pick_aoi")
async def pick_aoi(
    question: str,
    area_of_interest: Optional[AreaOfInterestType],
    state: Annotated[Dict, InjectedState],
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Resolve the place(s) in the user's request to map geometry (the AOI).

    Pass the user's request describing WHERE to analyze, verbatim — e.g.
    "tree cover loss in Para, Brazil", "compare deforestation across the
    districts of Odisha", "protected areas in Peru", "forest loss worldwide".

    This geocoding subagent does its own reasoning: it extracts place name(s),
    translates them to English, decides whether the user wants a single area
    or a comparison across subregions, and handles global ("worldwide")
    queries. You do NOT need to parse, translate, or classify the place — just
    forward what the user asked.

    Updates the AOI selection in state. If the place is ambiguous or missing,
    it returns a clarifying question for the user instead.
    """
    language = (state or {}).get("language") or DEFAULT_LANGUAGE
    return await Geocoder().resolve(
        question, area_of_interest, tool_call_id, language
    )


SPEC = ToolSpec(
    tool=pick_aoi,
    category=ToolCategory.SUBAGENT,
    prompt_fragment='- pick_aoi(question): natural-language geocoder. Pass the place request verbatim ("tree cover loss in Pará, Brazil", "the districts of Odisha", "forest loss worldwide"). If there is an obvious type of area of interest, then specify as that well. It extracts, translates and resolves the place — and any subregions — itself. Updates the AOI in state, or returns a clarifying question.',
)
