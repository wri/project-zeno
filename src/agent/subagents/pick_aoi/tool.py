import asyncio
import unicodedata
from difflib import SequenceMatcher
from enum import StrEnum
from typing import (
    Annotated,
    Any,
    Dict,
    Literal,
    Optional,
    Sequence,
    Union,
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
from src.agent.subagents.pick_aoi.selection_name_util import (
    build_selection_name,
)
from src.agent.subagents.progress import emit_progress
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.send_nudge import NUDGE_ALREADY_SET_NOTE
from src.shared.database import get_connection_from_pool
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
    if len(populated) == 1:
        return populated[0], primary

    combined = pd.concat(populated, ignore_index=True)
    if "similarity_score" in combined.columns:
        # Stable sort, so rows tied on score keep term order: the merge is
        # deterministic for identical inputs.
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


# ---------------------------------------------------------------------------
# Deterministic candidate scoring (PZB-1272).
#
# Retrieval and selection need different comparisons. `search_aois` ranks by
# pg_trgm similarity over the whole stored name, which is accent-sensitive:
# for the query "Para" it puts "Paraná" ABOVE "Pará", because the accent
# breaks Pará's trigrams. Selection therefore re-scores the retrieved rows in
# Python, accent-insensitively, instead of asking a model to repair the
# ranking.
# ---------------------------------------------------------------------------

_SIMILARITY_WEIGHT = 0.5
_HIERARCHY_WEIGHT = 0.3
_EXACT_SEGMENT_BONUS = 0.2
_PREFIX_BONUS = 0.1

# Punctuation that can wrap a name segment. Stored names carry trailing
# commas ("NA, England, United Kingdom"), and an `aoi_choice` nudge option is
# resubmitted verbatim as the next question ("Paris, Ile-de-France, France -
# (district-county) [FRA]"), so a segment comparison that keeps punctuation
# would never match the same place spelled plainly.
_SEGMENT_PUNCTUATION = " \t.,;:!?'\"()[]-"

# Preference by subtype: broader admin units beat narrower ones, and admin
# units beat named sites (KBA/WDPA/Landmark), so a bare "Lisbon" resolves to
# the Portuguese district rather than a small "Lisbon Forest Preserve". These
# ten values are everything `search_aois` can emit.
_HIERARCHY_SCORES: dict[str, float] = {
    "country": 1.0,
    "state-province": 0.9,
    "district-county": 0.7,
    "custom-area": 0.7,
    "municipality": 0.5,
    "locality": 0.35,
    "neighbourhood": 0.25,
    "key-biodiversity-area": 0.2,
    "protected-area": 0.2,
    "indigenous-and-community-land": 0.2,
}


def _strip_accents(text_value: str) -> str:
    """Lowercase and remove diacritics: "Pará" -> "para"."""
    decomposed = unicodedata.normalize("NFD", text_value.lower())
    return "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )


def _first_segment(name: str) -> str:
    """The leaf name: first comma-separated segment, accent-stripped.

    Stored names are comma-joined most-specific-first ("Pará, Brazil";
    "Botum Sakor, ..., KHM") and the geocoder emits "Place, Parent" strings,
    so the first segment is the place's own name.
    """
    leaf = name.split(",")[0]
    return _strip_accents(leaf).strip(_SEGMENT_PUNCTUATION)


def _score_candidate(place_name: str, name: str, subtype: str) -> float:
    """Composite score for one AOI candidate against one search term.

    Weighted sum of accent-insensitive string similarity and an admin
    hierarchy preference, plus an exact-leaf-name bonus that falls back to a
    weaker prefix bonus. The leaf bonus is what separates "Pará" from
    "Paraná" for the term "Para".

    Raises:
        ValueError: If ``subtype`` is not a known AOI subtype.
    """
    if subtype not in _HIERARCHY_SCORES:
        raise ValueError(f"Unknown AOI subtype: {subtype!r}")

    term = _strip_accents(place_name)
    candidate = _strip_accents(name)

    similarity = SequenceMatcher(None, term, candidate).ratio()
    score = _SIMILARITY_WEIGHT * similarity
    score += _HIERARCHY_WEIGHT * _HIERARCHY_SCORES[subtype]

    if _first_segment(place_name) == _first_segment(name):
        score += _EXACT_SEGMENT_BONUS
    elif candidate.startswith(term):
        score += _PREFIX_BONUS

    return score


def score_best_aoi(
    candidate_aois: pd.DataFrame, terms: list[str]
) -> Optional[AOIIndex]:
    """Pick the best candidate deterministically, with no model call.

    Args:
        candidate_aois: Candidates from ``query_aoi_database`` or
            ``query_aoi_database_multiterm``.
        terms: The search terms this place was looked up under. A candidate
            keeps its BEST score across them, so a row that only a native
            spelling or an expanded acronym could find is not then penalised
            for mismatching the term the user typed.

    Returns:
        The highest scoring candidate, or None when there are none. None
        rather than an exception keeps the contract of the LLM selection this
        replaces: ``Geocoder.lookup`` reports the place as unmatched.

    Raises:
        ValueError: If ``terms`` is empty, or a candidate carries a subtype
            that is not in the hierarchy map.
    """
    if candidate_aois.empty:
        logger.debug("No candidate AOIs to select from")
        return None
    if not terms:
        raise ValueError("score_best_aoi needs at least one search term")

    scored = [
        (
            max(
                _score_candidate(term, row["name"], row["subtype"])
                for term in terms
            ),
            row,
        )
        for row in candidate_aois.to_dict(orient="records")
    ]
    # Sort with explicit secondary keys rather than taking a max, so equal
    # scores resolve identically whatever order the rows arrived in.
    scored.sort(
        key=lambda pair: (
            -pair[0],
            pair[1]["name"],
            pair[1]["source"],
            str(pair[1]["src_id"]),
        )
    )
    best_score, best_row = scored[0]
    # The score stays out of the row: AOIIndex allows extra fields, so a
    # score written back onto the DataFrame would leak into aoi_selection.
    selected_aoi = AOIIndex(**best_row)

    logger.debug(
        f"Selected AOI {selected_aoi.src_id} scoring {best_score:.3f} "
        f"from {len(scored)} candidate(s) for terms {terms}"
    )
    return selected_aoi


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

    # Chain for selecting the best location match and returning the src_id
    AOI_SELECTION_CHAIN = (
        AOI_SELECTION_PROMPT | SMALL_MODEL.with_structured_output(AOIId)
    )

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


def _search_terms(place: ExtractedPlace, normalized: bool) -> list[str]:
    """The terms to search for one place, most authoritative first.

    The extracted place name always leads and is always searched, so
    normalisation can only add candidates — it can never remove the row that
    the place name alone would have found. With the normaliser disabled the
    term set collapses to that one name, which is the pre-PZB-1272 search.
    """
    terms = [place.place]
    if not normalized:
        return terms
    for candidate in [place.canonical, *place.alternatives]:
        if candidate and candidate not in terms:
            terms.append(candidate)
    return terms


def _effective_aoi_type(
    place: ExtractedPlace,
    aoi_type: Optional[AreaOfInterestType],
    normalized: bool,
) -> Optional[AreaOfInterestType]:
    """The source restriction for one place.

    The orchestrator's explicit `area_of_interest` wins; the type the
    geocoder inferred for this place only fills the gap when the
    orchestrator gave none.
    """
    if aoi_type is not None:
        return aoi_type
    if not normalized:
        return None
    return place.area_type


async def _search_candidates(
    place: ExtractedPlace,
    terms: list[str],
    aoi_type: Optional[AreaOfInterestType],
    normalized: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Search one place's terms, narrowed to a source when one is known.

    Narrowing carries weight now that the designation no longer travels in
    the search term: with the whole catalogue in scope, an admin unit that
    shares a park's leaf name outranks the park on the hierarchy term alone.
    A wrong type must not cost recall, though, so an empty narrowed result is
    retried across every source.
    """
    effective_type = _effective_aoi_type(place, aoi_type, normalized)
    merged, primary = await query_aoi_database_multiterm(
        terms, effective_type, RESULT_LIMIT
    )
    if merged.empty and normalized and effective_type is not None:
        logger.info(
            "GEOCODER: no %s candidates for %r; retrying every source",
            effective_type,
            place.place,
        )
        merged, primary = await query_aoi_database_multiterm(
            terms, None, RESULT_LIMIT
        )
    return merged, primary


def _as_extracted_place(place: Union[str, ExtractedPlace]) -> ExtractedPlace:
    """Accept a bare place name where an ExtractedPlace is expected.

    `Geocoder.lookup` is also called directly with plain place strings — by
    the tools and agent test suites, and by anything that already knows the
    place name. A bare string means "no normalisation available", which is
    exactly an ExtractedPlace carrying only `place`.
    """
    if isinstance(place, ExtractedPlace):
        return place
    return ExtractedPlace(place=place)


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
        )

    async def extract(
        self, question: str, aoi_type: Optional[AreaOfInterestType]
    ) -> PlaceQuery:
        """LLM step: turn the user's request into place(s) + subregion."""
        chain = (
            GEOCODER_EXTRACTION_PROMPT
            | SMALL_MODEL.with_structured_output(PlaceQuery)
        )
        return await chain.ainvoke({"question": question})

    async def lookup(
        self,
        question: str,
        # Sequence, not list: `resolve` passes a list[ExtractedPlace] and
        # list is invariant.
        places: Sequence[Union[str, ExtractedPlace]],
        subregion: Optional[SubregionType] = None,
        aoi_type: Optional[AreaOfInterestType] = None,
        tool_call_id: Optional[str] = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> Command:
        """DB step: resolve known place name(s) to AOI geometry."""
        extracted = [_as_extracted_place(place) for place in places]
        place_names = [place.place for place in extracted]
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
        term_sets = [_search_terms(place, normalized) for place in extracted]
        for place, terms in zip(place_names, term_sets):
            if len(terms) > 1:
                emit_progress(
                    "pick_aoi",
                    "normalize",
                    f"Searching '{place}' as: {'; '.join(terms)}",
                )

        searches = await asyncio.gather(
            *[
                _search_candidates(place, terms, aoi_type, normalized)
                for place, terms in zip(extracted, term_sets)
            ]
        )
        all_results = [merged for merged, _ in searches]
        primary_results = [primary for _, primary in searches]
        for place, result in zip(place_names, all_results):
            names = list(result["name"]) if "name" in result.columns else []
            emit_progress(
                "pick_aoi",
                "candidates",
                f"Fuzzy search '{place}': {len(names)} candidate(s)"
                + (f" — {'; '.join(names[:8])}" if names else ""),
            )

        selected_aois_raw: list[Optional[AOIIndex]]
        if normalized:
            # No model chooses among candidates: identical candidates always
            # produce the identical AOI.
            selected_aois_raw = [
                score_best_aoi(result, terms)
                for result, terms in zip(all_results, term_sets)
            ]
        else:
            selected_aois_raw = list(
                await asyncio.gather(
                    *[
                        select_best_aoi(question, result)
                        for result in all_results
                    ]
                )
            )
        unmatched_places = [
            place
            for place, aoi in zip(place_names, selected_aois_raw)
            if aoi is None
        ]
        # Pair each selection with the candidates of ITS OWN place. Zipping
        # the filtered selections against the unfiltered frames would pair a
        # selection with another place's candidates as soon as one place
        # matched nothing.
        matched = [
            (aoi, primary)
            for aoi, primary in zip(selected_aois_raw, primary_results)
            if aoi is not None
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

        if subregion:
            subregion_tasks = [
                query_subregion_database(
                    subregion, selected_aoi.source, selected_aoi.src_id
                )
                for selected_aoi in selected_aois
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
            match_names, subregion, len(final_aois)
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
