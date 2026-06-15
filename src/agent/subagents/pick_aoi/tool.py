import asyncio
from typing import Annotated, Literal, Optional

import pandas as pd
import structlog
from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

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
from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import (
    CUSTOM_AREA_TABLE,
    GADM_STANDARD_ID_RE,
    GADM_TABLE,
    KBA_TABLE,
    LANDMARK_TABLE,
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
    WDPA_TABLE,
)
from src.shared.logging_config import get_logger

RESULT_LIMIT = 10
SUBREGION_LIMIT_ADMIN = 1000
SUBREGION_LIMIT = 50

load_dotenv()
logger = get_logger(__name__)


def _antimeridian_bbox_sql(geom_expr: str) -> str:
    """
    Returns [west, south, east, north] JSON array.
    For antimeridian-crossing geometries (span > 180°), clips to each
    half-plane to get the bbox of the eastern and western parts separately —
    no ST_Dump, no vertex iteration. Falls back to naive bbox if either
    clip returns nothing (geometry doesn't truly cross the antimeridian).
    """
    east_half = "ST_MakeEnvelope(0, -90, 180, 90, 4326)"
    west_half = "ST_MakeEnvelope(-180, -90, 0, 90, 4326)"
    return f"""
    CASE
        WHEN ST_XMax({geom_expr}) - ST_XMin({geom_expr}) > 180
        THEN (
            SELECT COALESCE(
                CASE
                    WHEN west IS NOT NULL AND east IS NOT NULL
                    THEN json_build_array(west, ST_YMin({geom_expr}), east, ST_YMax({geom_expr}))
                END,
                json_build_array(ST_XMin({geom_expr}), ST_YMin({geom_expr}), ST_XMax({geom_expr}), ST_YMax({geom_expr}))
            )
            FROM (
                SELECT
                    ST_XMin(ST_Envelope(ST_ClipByBox2D({geom_expr}, {east_half}))) AS west,
                    ST_XMax(ST_Envelope(ST_ClipByBox2D({geom_expr}, {west_half}))) AS east
            ) AS parts
        )
        ELSE json_build_array(
            ST_XMin({geom_expr}),
            ST_YMin({geom_expr}),
            ST_XMax({geom_expr}),
            ST_YMax({geom_expr})
        )
    END
    """


BBOX_SQL = f"({_antimeridian_bbox_sql('geometry')}) AS bbox"

# The custom geometries table stores geometries as an list of geojsons,
# requiring a funky SQL to pull out the overall bounds
CUSTOM_BBOX_SQL = f"""
(
    SELECT {_antimeridian_bbox_sql("bounds.geometry")}
    FROM (
        SELECT ST_Envelope(
            ST_Collect(ST_SetSRID(ST_GeomFromGeoJSON(geom_json), 4326))
        ) AS geometry
        FROM jsonb_array_elements_text(geometries) AS geom(geom_json)
    ) AS bounds
) AS bbox
"""


async def fetch_aoi_bbox(source: str, src_id: str) -> list[float]:
    """Look up bbox for an AOI by source and src_id, using the same antimeridian-aware SQL as pick_aoi."""
    if source not in SOURCE_ID_MAPPING:
        return [-180.0, -90.0, 180.0, 90.0]

    table = SOURCE_ID_MAPPING[source]["table"]
    id_column = SOURCE_ID_MAPPING[source]["id_column"]
    bbox_expr = CUSTOM_BBOX_SQL if source == "custom" else BBOX_SQL

    query = text(
        f"SELECT {bbox_expr} FROM {table} WHERE {id_column} = :src_id"
    )
    async with get_connection_from_pool() as conn:
        result = await conn.execute(query, {"src_id": src_id})
        row = result.fetchone()
        if row and row[0]:
            return row[0]
    return [-180.0, -90.0, 180.0, 90.0]


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
    aoi_type: Optional[str],
    result_limit: int = 10,
):
    """Query the PostGIS database for location information.

    Args:
        place_name: Name of the place to search for
        aoi_type: Specific AOI table to search, or None to search all
        result_limit: Maximum number of results to return

    Returns:
        DataFrame containing location information
    """
    async with get_connection_from_pool() as conn:
        # Enable pg_trgm extension for similarity function
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.execute(text("SET pg_trgm.similarity_threshold = 0.2;"))
        await conn.commit()

        user_id = structlog.contextvars.get_contextvars().get("user_id")

        # Check which tables exist first
        existing_tables = []

        # Check GADM table
        try:
            await conn.execute(text(f"SELECT 1 FROM {GADM_TABLE} LIMIT 1"))
            existing_tables.append("gadm")
        except Exception:
            logger.warning(f"Table {GADM_TABLE} does not exist")
            await conn.rollback()

        # Check KBA table
        try:
            await conn.execute(text(f"SELECT 1 FROM {KBA_TABLE} LIMIT 1"))
            existing_tables.append("kba")
        except Exception:
            logger.warning(f"Table {KBA_TABLE} does not exist")
            await conn.rollback()

        # Check Landmark table
        try:
            await conn.execute(text(f"SELECT 1 FROM {LANDMARK_TABLE} LIMIT 1"))
            existing_tables.append("landmark")
        except Exception:
            logger.warning(f"Table {LANDMARK_TABLE} does not exist")
            await conn.rollback()

        # Check WDPA table
        try:
            await conn.execute(text(f"SELECT 1 FROM {WDPA_TABLE} LIMIT 1"))
            existing_tables.append("wdpa")
        except Exception:
            logger.warning(f"Table {WDPA_TABLE} does not exist")
            await conn.rollback()

        # Check Custom Areas table
        try:
            await conn.execute(
                text(f"SELECT 1 FROM {CUSTOM_AREA_TABLE} LIMIT 1")
            )
            existing_tables.append("custom")
        except Exception:
            logger.warning(f"Table {CUSTOM_AREA_TABLE} does not exist")
            await conn.rollback()

        # Build the query based on existing tables
        union_parts = []

        if aoi_type is not None:
            if aoi_type in existing_tables:
                existing_tables = [aoi_type]
            else:
                # This cannot happen in production, unless the AOI tables are
                # misconfigured. This is to catch the case where not all tables have
                # been created locally.
                raise ValueError(
                    f"Required geometry table {aoi_type} does not exist in the database"
                )

        if "gadm" in existing_tables:
            union_parts.append(
                f"""
                SELECT gadm_id AS src_id,
                    name, subtype, 'gadm' as source, {BBOX_SQL}
                FROM {GADM_TABLE}
                WHERE name IS NOT NULL AND name % :place_name
                AND gadm_id ~ '{GADM_STANDARD_ID_RE}'
            """
            )

        if "kba" in existing_tables:
            src_id = SOURCE_ID_MAPPING["kba"]["id_column"]
            union_parts.append(
                f"""
                SELECT CAST({src_id} as TEXT) as src_id,
                       name,
                       subtype,
                       'kba' as source,
                       {BBOX_SQL}
                FROM {KBA_TABLE}
                WHERE name IS NOT NULL AND name % :place_name
            """
            )

        if "landmark" in existing_tables:
            src_id = SOURCE_ID_MAPPING["landmark"]["id_column"]
            union_parts.append(
                f"""
                SELECT CAST({src_id} as TEXT) as src_id,
                       name,
                       subtype,
                       'landmark' as source,
                       {BBOX_SQL}
                FROM {LANDMARK_TABLE}
                WHERE name IS NOT NULL AND name % :place_name
            """
            )

        if "wdpa" in existing_tables:
            src_id = SOURCE_ID_MAPPING["wdpa"]["id_column"]
            union_parts.append(
                f"""
                SELECT CAST({src_id} as TEXT) as src_id,
                       name,
                       subtype,
                       'wdpa' as source,
                       {BBOX_SQL}
                FROM {WDPA_TABLE}
                WHERE name IS NOT NULL AND name % :place_name
            """
            )
        if "custom" in existing_tables:
            src_id = SOURCE_ID_MAPPING["custom"]["id_column"]
            if not user_id:
                raise ValueError("user_id required for custom areas")

            union_parts.append(
                f"""
                SELECT CAST({src_id} as TEXT) as src_id,
                        name,
                        'custom-area' as subtype,
                        'custom' as source,
                        {CUSTOM_BBOX_SQL}
                FROM {CUSTOM_AREA_TABLE}
                WHERE user_id = :user_id
                AND name IS NOT NULL AND name % :place_name
            """
            )

        if not union_parts:
            logger.error("No geometry tables exist in the database")
            return pd.DataFrame()

        # Create the combined search query
        combined_query = " UNION ALL ".join(union_parts)

        sql_query = f"""
            WITH combined_search AS (
                {combined_query}
            )
            SELECT *,
                   similarity(LOWER(name), LOWER(:place_name)) AS similarity_score
            FROM combined_search
            WHERE name IS NOT NULL
            AND name % :place_name
            ORDER BY similarity_score DESC
            LIMIT :limit_val
        """

        logger.debug(f"Executing AOI query: {sql_query}")

        def _read(sync_conn):
            return pd.read_sql(
                text(sql_query),
                sync_conn,
                params={
                    "place_name": place_name,
                    "limit_val": result_limit,
                    "user_id": user_id,
                },
            )

        query_results = await conn.run_sync(_read)

    logger.debug(f"AOI query results: {query_results}")
    return query_results


async def query_subregion_database(
    subregion_name: str, source: str, src_id: str
):
    """Query the right table in PostGIS database for subregions based on the selected AOI.

    Args:
        subregion_name: Name of the subregion to search for
        source: Source of the selected AOI
        src_id: id of the selected AOI in source table: gadm_id, kba_id, landmark_id, wdpa_id

    Returns:
        DataFrame of subregions
    """
    match subregion_name:
        case (
            "country"
            | "state"
            | "district"
            | "municipality"
            | "locality"
            | "neighbourhood"
        ):
            table_name = GADM_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING[subregion_name]
            subregion_source = "gadm"
            src_id_field = SOURCE_ID_MAPPING["gadm"]["id_column"]
        case "kba":
            table_name = KBA_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["kba"]
            subregion_source = "kba"
            src_id_field = SOURCE_ID_MAPPING["kba"]["id_column"]
        case "wdpa":
            table_name = WDPA_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["wdpa"]
            subregion_source = "wdpa"
            src_id_field = SOURCE_ID_MAPPING["wdpa"]["id_column"]
        case "landmark":
            table_name = LANDMARK_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["landmark"]
            subregion_source = "landmark"
            src_id_field = SOURCE_ID_MAPPING["landmark"]["id_column"]
        case _:
            logger.error(f"Invalid subregion: {subregion_name}")
            raise ValueError(
                f"Subregion: {subregion_name} does not match to any table in PostGIS database."
            )

    id_column = SOURCE_ID_MAPPING[source]["id_column"]
    source_table = SOURCE_ID_MAPPING[source]["table"]

    logger.info(
        f"Querying subregion: {subregion_name} in table: {table_name} for source: {source}, src_id: {src_id}"
    )

    if table_name == GADM_TABLE:
        if source == "gadm":
            # remove _1/_2 GADM suffix
            if "_" in src_id:
                subregion_filter = src_id.split("_")[0]
            else:
                subregion_filter = src_id

            # filter for the next admin level within this admin ID
            gadm_filter = f" AND t.gadm_id LIKE '{subregion_filter}.%'"
        else:
            gadm_filter = f" AND t.gadm_id ~ '{GADM_STANDARD_ID_RE}'"
        spatial_filter = ""
    else:
        gadm_filter = ""
        spatial_filter = " AND ST_Intersects(t.geometry, aoi.geom) AND NOT ST_Touches(t.geometry, aoi.geom)"

    sql_query = f"""
    WITH aoi AS (
        SELECT geometry AS geom
        FROM {source_table}
        WHERE "{id_column}" = :src_id
        LIMIT 1
    )
    SELECT t.name, t.subtype, t.{src_id_field}, '{subregion_source}' as source, t.{src_id_field} as src_id, {BBOX_SQL}
    FROM {table_name} AS t, aoi
    WHERE t.subtype = :subtype
    {gadm_filter}
    {spatial_filter}
    """
    logger.debug(f"Executing subregion query: {sql_query}")

    async with get_connection_from_pool() as conn:

        def _read(sync_conn):
            processed_src_id = src_id
            if source == "kba":
                # for these sources IDs stored as numeric values
                try:
                    processed_src_id = int(processed_src_id)
                except ValueError:
                    pass
            return pd.read_sql(
                text(sql_query),
                sync_conn,
                params={"src_id": processed_src_id, "subtype": subtype},
            )

        results = await conn.run_sync(_read)

    return results


async def select_best_aoi(
    question: str, candidate_aois: pd.DataFrame
) -> AOIIndex:
    """Select the best AOI based on the user query.

    Args:
        question: User's question providing context for selecting the most relevant location
        candidate_aois: Candidate AOIs to select from

    Returns:
        Selected AOI: AOIIndex
    """
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
    selected_aoi_row = candidate_aois[
        candidate_aois["src_id"] == selected_aoi_index.src_id
    ].iloc[0]
    selected_aoi = AOIIndex(**selected_aoi_row.to_dict())

    logger.debug(f"Candidate AOIs: {candidate_aois}")
    logger.debug(f"Selected AOI: {selected_aoi}")

    return selected_aoi


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

    return None


async def check_aoi_selection(aois: list[AOIIndex]) -> Optional[str]:
    if not aois:
        return (
            "No matching AOIs were found for your request. "
            "Try a broader place name or choose a different subregion type."
        )

    aoi_sources = set([aoi.source for aoi in aois])
    if len(aoi_sources) > 1:
        return "Found multiple sources of AOIs, which is not supported. Please select only one source."

    aoi_source = next(iter(aoi_sources))
    if aoi_source in {"kba", "wdpa", "landmark"}:
        subregion_limit = SUBREGION_LIMIT
    else:
        subregion_limit = SUBREGION_LIMIT_ADMIN

    if len(aois) > subregion_limit:
        return (
            f"Found {len(aois)} subregions, which is too many to process efficiently. "
            "Please narrow down your search by either:\n"
            "1. Being more specific with the AOI selection (choose a smaller area)\n"
            "2. Being more specific with the subregion query (e.g., 'kbas' instead of 'areas')\n"
            f"For optimal performance, please limit results to under {SUBREGION_LIMIT} subregions for KBA, WDPA, and Indigenous Lands, or under {SUBREGION_LIMIT_ADMIN} for other area types."
        )

    return None


async def check_duplicate_aois(
    selected_aois: list[AOIIndex], all_results: list[pd.DataFrame]
) -> Optional[str]:
    for selected_aoi, result in zip(selected_aois, all_results):
        if selected_aoi.source == "gadm":
            short_name = selected_aoi.name.split(",")[0]
            candidate_names = await check_multiple_matches(
                selected_aoi.src_id, short_name, result
            )
            if candidate_names:
                return f"I found multiple locations named '{short_name}' in different countries. Please tell me which one you meant:\n\n{candidate_names}\n\nWhich location are you looking for?"

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

AOIType = Literal[
    "gadm",
    "wdpa",
    "landmark",
    "kba",
]


class PlaceQuery(BaseModel):
    """A place request the geocoder extracts from the user's message."""

    places: list[str] = Field(
        default_factory=list,
        description=(
            "English place name(s), one entry per distinct location. A place "
            "and its parent stay in one string, e.g. 'Lisbon, Portugal'."
        ),
    )
    subregion: Optional[SubregionType] = Field(
        default=None,
        description=(
            "Set only to compare or analyze across many administrative units "
            "inside the place(s); otherwise leave null."
        ),
    )
    aoi_type: Optional[AOIType] = Field(
        default=None,
        description=(
            "Set if user's query implies that the place names are a particular type of AOI;"
            "otherwise leave null."
        ),
    )


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
        self, question: str, tool_call_id: Optional[str] = None
    ) -> Command:
        """Full resolution: extract place(s) from the request, then look up."""
        query = await self.extract(question)
        print(query)
        logger.info(
            "GEOCODER: extracted places=%r subregion=%r",
            query.places,
            query.subregion,
        )
        if not query.places:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            "I couldn't identify a place in your request. "
                            "Which area would you like me to analyze?",
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
            query.aoi_type,
            tool_call_id,
        )

    async def extract(self, question: str) -> PlaceQuery:
        """LLM step: turn the user's request into place(s) + subregion."""
        chain = (
            GEOCODER_EXTRACTION_PROMPT
            | SMALL_MODEL.with_structured_output(PlaceQuery)
        )
        return await chain.ainvoke({"question": question})

    async def lookup(
        self,
        question: str,
        places: list[str],
        subregion: Optional[SubregionType] = None,
        aoi_type: Optional[AOIType] = None,
        tool_call_id: Optional[str] = None,
    ) -> Command:
        """DB step: resolve known place name(s) to AOI geometry."""
        logger.info(
            f"GEOCODER: lookup places: '{places}', subregion: '{subregion}'"
        )

        if is_global_request(places):
            logger.info("GEOCODER: global request detected")
            emit_progress("pick_aoi", "global", "Global (worldwide) request")
            return await handle_global_request(subregion, tool_call_id)

        all_results = await asyncio.gather(
            *[
                query_aoi_database(place, aoi_type, RESULT_LIMIT)
                for place in places
            ]
        )
        for place, result in zip(places, all_results):
            names = list(result["name"]) if "name" in result.columns else []
            emit_progress(
                "pick_aoi",
                "candidates",
                f"Fuzzy search '{place}': {len(names)} candidate(s)"
                + (f" — {'; '.join(names[:8])}" if names else ""),
            )

        selected_aois = await asyncio.gather(
            *[select_best_aoi(question, result) for result in all_results]
        )

        duplicate_check = await check_duplicate_aois(
            selected_aois, all_results
        )
        if duplicate_check:
            return Command(
                update={
                    "messages": [
                        ToolMessage(duplicate_check, tool_call_id=tool_call_id)
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
            tool_message += f"\n- {selected_aoi.name}"

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
    return await Geocoder().resolve(question, tool_call_id)
