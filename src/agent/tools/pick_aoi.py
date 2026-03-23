import asyncio
import unicodedata
from typing import Annotated, Literal, Optional

import pandas as pd
import structlog
from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.agent.tools.aoi_normalizer import (
    expand_geographic_concept,
    normalize_place_name,
)
from src.agent.tools.selection_name_util import build_selection_name
from src.shared.aoi.registry import all_sources, get_source
from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import (
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
)
from src.shared.logging_config import get_logger

RESULT_LIMIT = 10

load_dotenv()
logger = get_logger(__name__)


class AOIIndex(BaseModel):
    """Model for storing the best matched location."""

    source: str = Field(description="`source` of the best matched location.")
    src_id: str = Field(description="`src_id` of the best matched location.")
    name: str = Field(description="`name` of the best matched location.")
    subtype: str = Field(description="`subtype` of the best matched location.")


async def query_aoi_database(
    search_terms: list[str],
    result_limit: int = 10,
):
    """Query the PostGIS database for location information using multiple search terms.

    Searches across all source tables using trigram similarity for each term,
    deduplicates by (source, src_id) keeping the highest similarity score.

    Args:
        search_terms: List of place name variants to search for (primary + alternatives)
        result_limit: Maximum number of results to return

    Returns:
        DataFrame containing location information
    """
    if not search_terms:
        return pd.DataFrame()

    async with get_connection_from_pool() as conn:
        # Enable pg_trgm extension for similarity function
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.execute(text("SET pg_trgm.similarity_threshold = 0.2;"))
        await conn.commit()

        user_id = structlog.contextvars.get_contextvars().get("user_id")

        # Discover which source tables exist
        available_configs = []
        for config in all_sources():
            try:
                await conn.execute(
                    text(f"SELECT 1 FROM {config.table} LIMIT 1")
                )
                available_configs.append(config)
            except Exception:
                logger.warning(f"Table {config.table} does not exist")
                await conn.rollback()

        if not available_configs:
            logger.error("No geometry tables exist in the database")
            return pd.DataFrame()

        # Build UNION across all terms × all tables
        union_parts = []
        params: dict = {"limit_val": result_limit, "user_id": user_id}

        for term_idx, term in enumerate(search_terms):
            term_param = f"term_{term_idx}"
            params[term_param] = term

            for config in available_configs:
                source_val = config.source_type.value
                if source_val == "custom":
                    if not user_id:
                        raise ValueError("user_id required for custom areas")
                    union_parts.append(
                        f"""
                        SELECT CAST({config.id_column} as TEXT) as src_id,
                                name,
                                'custom-area' as subtype,
                                '{source_val}' as source,
                                similarity(LOWER(name), LOWER(:{term_param})) AS similarity_score
                        FROM {config.table}
                        WHERE user_id = :user_id
                        AND name IS NOT NULL AND name % :{term_param}
                    """
                    )
                elif source_val == "gadm":
                    union_parts.append(
                        f"""
                        SELECT {config.id_column} AS src_id,
                            name, subtype, '{source_val}' as source,
                            similarity(LOWER(name), LOWER(:{term_param})) AS similarity_score
                        FROM {config.table}
                        WHERE name IS NOT NULL AND name % :{term_param}
                    """
                    )
                else:
                    union_parts.append(
                        f"""
                        SELECT CAST({config.id_column} as TEXT) as src_id,
                               name,
                               subtype,
                               '{source_val}' as source,
                               similarity(LOWER(name), LOWER(:{term_param})) AS similarity_score
                        FROM {config.table}
                        WHERE name IS NOT NULL AND name % :{term_param}
                    """
                    )

        combined_query = " UNION ALL ".join(union_parts)

        # Deduplicate by (source, src_id), keeping highest similarity score
        sql_query = f"""
            WITH multi_search AS (
                {combined_query}
            ),
            deduplicated AS (
                SELECT DISTINCT ON (source, src_id) *
                FROM multi_search
                ORDER BY source, src_id, similarity_score DESC
            )
            SELECT * FROM deduplicated
            ORDER BY similarity_score DESC
            LIMIT :limit_val
        """

        logger.debug(
            f"Executing multi-term AOI query with {len(search_terms)} terms"
        )

        def _read(sync_conn):
            return pd.read_sql(
                text(sql_query),
                sync_conn,
                params=params,
            )

        query_results = await conn.run_sync(_read)

    logger.debug(f"AOI query results: {len(query_results)} rows")
    return query_results


async def query_subregion_database(
    subregion_name: str, source: str, src_id: int
):
    """Query the right table in PostGIS database for subregions based on the selected AOI.

    Args:
        subregion_name: Name of the subregion to search for
        source: Source of the selected AOI
        src_id: id of the selected AOI in source table: gadm_id, kba_id, landmark_id, wdpa_id

    Returns:
        DataFrame of subregions
    """
    subtype = SUBREGION_TO_SUBTYPE_MAPPING.get(subregion_name)
    if not subtype:
        logger.error(f"Invalid subregion: {subregion_name}")
        raise ValueError(
            f"Subregion: {subregion_name} does not match to any table in PostGIS database."
        )

    # Determine which source the subregion belongs to
    ADMIN_SUBREGIONS = {
        "country",
        "state",
        "district",
        "municipality",
        "locality",
        "neighbourhood",
    }
    if subregion_name in ADMIN_SUBREGIONS:
        subregion_source = "gadm"
    else:
        subregion_source = subregion_name  # kba, wdpa, landmark

    subregion_config = get_source(subregion_source)
    table_name = subregion_config.table
    src_id_field = subregion_config.id_column

    source_config = get_source(source)
    id_column = source_config.id_column
    source_table = source_config.table

    logger.info(
        f"Querying subregion: {subregion_name} in table: {table_name} for source: {source}, src_id: {src_id}"
    )

    sql_query = f"""
    WITH aoi AS (
        SELECT geometry AS geom
        FROM {source_table}
        WHERE "{id_column}" = :src_id
        LIMIT 1
    )
    SELECT t.name, t.subtype, t.{src_id_field}, '{subregion_source}' as source, t.{src_id_field} as src_id
    FROM {table_name} AS t, aoi
    WHERE t.subtype = :subtype
    AND ST_Within(t.geometry, aoi.geom)
    """
    logger.debug(f"Executing subregion query: {sql_query}")

    async with get_connection_from_pool() as conn:

        def _read(sync_conn):
            processed_src_id = source_config.coerce_id(src_id)
            return pd.read_sql(
                text(sql_query),
                sync_conn,
                params={"src_id": processed_src_id, "subtype": subtype},
            )

        results = await conn.run_sync(_read)

    return results


# Hierarchy preference scores — country > state > district > ...
_HIERARCHY_SCORES: dict[str, float] = {
    "country": 1.0,
    "state-province": 0.8,
    "district-county": 0.6,
    "municipality": 0.4,
    "locality": 0.2,
    "neighbourhood": 0.1,
    "key-biodiversity-area": 0.5,
    "protected-area": 0.5,
    "indigenous-and-community-land": 0.5,
    "custom-area": 0.7,
}


def _strip_accents(s: str) -> str:
    """Remove diacritics/accents: Pará→Para, São→Sao, Paraná→Parana."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _first_segment(name: str) -> str:
    """Extract the first comma-separated segment, accent-stripped and lowered."""
    return _strip_accents(name.split(",")[0].strip()).lower()


def _score_candidate(row: dict, place_name: str) -> float:
    """Deterministic composite score for an AOI candidate."""
    # Factor 1: String similarity from PostGIS (strongest signal)
    score = 0.5 * row.get("similarity_score", 0.0)

    # Factor 2: Hierarchy preference (country > state > district > ...)
    score += 0.3 * _HIERARCHY_SCORES.get(row.get("subtype", ""), 0.3)

    # Factor 3: Exact segment match (accent-insensitive) or prefix bonus
    # "Para" exactly matches "Pará" (both → "para" after stripping).
    # "Para" does NOT exactly match "Paraná" (→ "parana").
    name = row.get("name", "")
    query_seg = _first_segment(place_name)
    cand_seg = _first_segment(name)

    if cand_seg == query_seg:
        # Exact match after accent stripping → strong bonus
        score += 0.2
    elif _strip_accents(name.lower()).startswith(
        _strip_accents(place_name.lower())
    ):
        # Weaker prefix match (accent-insensitive)
        score += 0.1

    return score


def select_best_aoi(
    question: str, results_df: pd.DataFrame, place_name: str
) -> dict:
    """Select the best AOI using deterministic scoring.

    Args:
        question: User's question (reserved for future context-based scoring)
        results_df: DataFrame of candidates from query_aoi_database
        place_name: The original place name searched for

    Returns:
        Dict with source, src_id, name, subtype of the best match
    """
    if results_df.empty:
        raise ValueError("No candidate AOIs found")

    results_df = results_df.copy()
    results_df["composite_score"] = results_df.apply(
        lambda row: _score_candidate(row.to_dict(), place_name), axis=1
    )
    results_df = results_df.sort_values("composite_score", ascending=False)
    best = results_df.iloc[0]

    selected = AOIIndex(
        source=best["source"],
        src_id=str(best["src_id"]),
        name=best["name"],
        subtype=best["subtype"],
    )
    logger.debug(f"Deterministic scorer selected: {selected}")

    try:
        get_source(selected.source)
    except (ValueError, KeyError):
        raise ValueError(
            f"Source: {selected.source} does not match to any table in PostGIS database."
        )

    return selected.model_dump()


async def check_multiple_matches(
    src_id: str, short_name: str, results: pd.DataFrame
) -> Optional[str]:
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

            candidate_names = all_matches[
                ["name", "subtype", "src_id"]
            ].to_dict(orient="records")
            return "\n".join(
                [
                    f"{candidate['name']} - ({candidate['subtype']}) [{candidate['src_id'].split('.')[0]}]"
                    for candidate in candidate_names
                ]
            )


async def check_aoi_selection(aois: list[dict]) -> str:
    aoi_sources = set([aoi["source"] for aoi in aois])
    if len(aoi_sources) > 1:
        return "Found multiple sources of AOIs, which is not supported. Please select only one source."

    aoi_source = next(iter(aoi_sources))
    subregion_limit = get_source(aoi_source).subregion_limit

    if len(aois) > subregion_limit:
        return (
            f"Found {len(aois)} subregions, which is too many to process efficiently. "
            "Please narrow down your search by either:\n"
            "1. Being more specific with the AOI selection (choose a smaller area)\n"
            "2. Being more specific with the subregion query (e.g., 'kbas' instead of 'areas')\n"
            "For optimal performance, please limit results to under 25 subregions for KBA, WDPA, and Indigenous Lands, or under 50 for other area types."
        )


async def check_duplicate_aois(
    selected_aois: list[dict], all_results: list[pd.DataFrame]
) -> str:
    for selected_aoi, result in zip(selected_aois, all_results):
        if selected_aoi["source"] == "gadm":
            short_name = selected_aoi["name"].split(",")[0]
            candidate_names = await check_multiple_matches(
                selected_aoi["src_id"], short_name, result
            )
            if candidate_names:
                return f"I found multiple locations named '{short_name}' in different countries. Please tell me which one you meant:\n\n{candidate_names}\n\nWhich location are you looking for?"


@tool("pick_aoi")
async def pick_aoi(
    question: str,
    places: list[str],
    subregion: Optional[
        Literal[
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
    ] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """Selects the most appropriate area of interest (AOI) based on a place name and user's question. Optionally, it can also filter the results by a subregion.

    This tool queries a spatial database to find location matches for a given place name.
    Place names are automatically normalized (translated, transliterated, accent-removed)
    and geographic concepts (biomes, regions, groupings) are expanded into admin units.

    Pass place names exactly as the user provided them — the tool handles normalization internally.

    Keep pairs of places together in one place name if they belong to the same place denomination.
    For example, "Lisbon in Portugal" -> "Lisbon, Portugal", do not separate them into "Lisbon" and "Portugal".

    Args:
        question: User's question providing context for selecting the most relevant location
        places: Names of the places or areas to find in the spatial database
        subregion: Specific subregion type to filter results by (optional). Must be one of: "country", "state", "district", "municipality", "locality", "neighbourhood", "kba", "wdpa", or "landmark".
    """
    logger.info(f"PICK-AOI-TOOL: places: '{places}', subregion: '{subregion}'")

    # Phase 1: Normalize all place names via Flash Lite (parallel).
    # The normalizer also sets is_concept=True for geographic concepts (biomes,
    # coastlines, river basins, informal regions) that would not exist as named
    # rows in GADM/WDPA/KBA/Landmark — allowing us to skip the DB search and go
    # straight to concept expansion for those terms.
    normalized = await asyncio.gather(
        *[normalize_place_name(place) for place in places]
    )

    # Phase 2: Query DB with primary + alternatives for each place.
    # Skip DB search when the normalizer flagged the term as a geographic concept —
    # the concept expansion in Phase 3 will handle it.
    async def _db_or_empty(norm):
        if norm.is_concept:
            return pd.DataFrame()
        return await query_aoi_database(
            [norm.primary] + norm.alternatives, RESULT_LIMIT
        )

    all_results = await asyncio.gather(*[_db_or_empty(n) for n in normalized])

    # Phase 3: For places with no DB results (or flagged as concepts), try concept expansion
    final_places = []
    final_results = []
    concept_coverage_notes = []

    for place, norm, result_df in zip(places, normalized, all_results):
        best_score = (
            result_df.iloc[0]["similarity_score"] if not result_df.empty else 0
        )
        if norm.is_concept or result_df.empty or best_score < 0.3:
            if norm.is_concept:
                logger.info(
                    f"Normalizer flagged '{place}' as geographic concept — skipping DB search"
                )
            # No good match or semantic concept — try geographic concept expansion
            expansion = await expand_geographic_concept(place, question)
            if expansion.is_concept and expansion.places:
                logger.info(
                    f"Expanded concept '{place}' into {len(expansion.places)} places"
                )
                concept_coverage_notes.append(expansion.coverage_note)

                # If concept has a source_hint and no subregion was specified,
                # use it (e.g., "protected areas in X" → subregion=wdpa)
                if expansion.source_hint and not subregion:
                    subregion = expansion.source_hint

                # Re-query for each expanded place
                expanded_norms = await asyncio.gather(
                    *[normalize_place_name(p) for p in expansion.places]
                )
                expanded_results = await asyncio.gather(
                    *[
                        query_aoi_database(
                            [n.primary] + n.alternatives,
                            RESULT_LIMIT,
                        )
                        for n in expanded_norms
                    ]
                )
                for exp_place, exp_result in zip(
                    expansion.places, expanded_results
                ):
                    final_places.append(exp_place)
                    final_results.append(exp_result)
            else:
                # Not a concept — keep original (may produce "not found")
                final_places.append(norm.primary)
                final_results.append(result_df)
        else:
            final_places.append(norm.primary)
            final_results.append(result_df)

    # Phase 4: Deterministic scorer selects best match for each place
    selected_aois = []
    valid_results = []
    for place, result_df in zip(final_places, final_results):
        if result_df.empty:
            logger.warning(f"No results found for '{place}', skipping")
            continue
        selected_aois.append(select_best_aoi(question, result_df, place))
        valid_results.append(result_df)

    if not selected_aois:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Could not find any matching locations for: {', '.join(places)}. "
                        "Please try with more specific place names.",
                        tool_call_id=tool_call_id,
                    )
                ],
            },
        )

    all_results = valid_results

    duplicate_check = await check_duplicate_aois(selected_aois, all_results)
    if duplicate_check:
        return Command(
            update={
                "messages": [
                    ToolMessage(duplicate_check, tool_call_id=tool_call_id)
                ],
            },
        )

    match_names = [selected_aoi["name"] for selected_aoi in selected_aois]

    if subregion:
        subregion_tasks = [
            query_subregion_database(
                subregion, selected_aoi["source"], selected_aoi["src_id"]
            )
            for selected_aoi in selected_aois
        ]
        subregion_dfs = await asyncio.gather(*subregion_tasks)
        final_aois = []
        for df in subregion_dfs:
            final_aois.extend(df.to_dict(orient="records"))
    else:
        final_aois = selected_aois

    logger.info(f"Found {len(final_aois)} AOIs in total")

    check = await check_aoi_selection(final_aois)
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
        selected_aoi[
            SOURCE_ID_MAPPING[selected_aoi["source"]]["id_column"]
        ] = selected_aoi["src_id"]
        tool_message += f"\n- {selected_aoi['name']}"

    # Append coverage notes from concept expansion if any
    if concept_coverage_notes:
        tool_message += "\n\nNote: " + " ".join(
            note for note in concept_coverage_notes if note
        )

    logger.debug(f"Pick AOI tool message: {tool_message}")

    selection_name = build_selection_name(
        match_names, subregion, len(final_aois)
    )

    return Command(
        update={
            "aoi_selection": {
                "name": selection_name,
                "aois": final_aois,
            },
            # TODO: This is deprecated, remove it in the future
            "aoi": final_aois[0],
            "subtype": final_aois[0]["subtype"],
            "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
        },
    )
