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
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.agent.llms import SMALL_MODEL
from src.shared.database import get_connection_from_pool
from src.shared.geocoding_helpers import (
    CUSTOM_AREA_TABLE,
    GADM_TABLE,
    KBA_TABLE,
    LANDMARK_TABLE,
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
    WDPA_TABLE,
)
from src.shared.logging_config import get_logger

RESULT_LIMIT = 10
SUBREGION_LIMIT = 50
SUBREGION_LIMIT_KBA = 25

load_dotenv()
logger = get_logger(__name__)


async def query_aoi_database(
    place_name: str,
    result_limit: int = 10,
):
    """Query the PostGIS database for location information.

    Args:
        place_name: Name of the place to search for
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

        if "gadm" in existing_tables:
            union_parts.append(
                f"""
                SELECT gadm_id AS src_id,
                    name, subtype, 'gadm' as source
                FROM {GADM_TABLE}
                WHERE name IS NOT NULL AND name % :place_name
            """
            )

        if "kba" in existing_tables:
            src_id = SOURCE_ID_MAPPING["kba"]["id_column"]
            union_parts.append(
                f"""
                SELECT CAST({src_id} as TEXT) as src_id,
                       name,
                       subtype,
                       'kba' as source
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
                       'landmark' as source
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
                       'wdpa' as source
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
                       'custom' as source
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


async def select_best_aoi(question, candidate_aois):
    """Select the best AOI based on the user query.

    Args:
        question: User's question providing context for selecting the most relevant location
        candidate_aois: Candidate AOIs to select from

    Returns:
        Selected AOI: AOIIndex
    """

    class AOIIndex(BaseModel):
        """Model for storing the best matched location."""

        source: str = Field(
            description="`source` of the best matched location."
        )
        src_id: str = Field(
            description="`src_id` of the best matched location."
        )
        name: str = Field(description="`name` of the best matched location.")
        subtype: str = Field(
            description="`subtype` of the best matched location."
        )

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
                {candidate_locations}

                User query:
                {user_query}
                """,
            )
        ]
    )

    # Chain for selecting the best location match
    AOI_SELECTION_CHAIN = (
        AOI_SELECTION_PROMPT | SMALL_MODEL.with_structured_output(AOIIndex)
    )

    selected_aoi = await AOI_SELECTION_CHAIN.ainvoke(
        {"candidate_locations": candidate_aois, "user_query": question}
    )
    logger.debug(f"Candidate locations: {candidate_aois}")
    logger.debug(f"Selected AOI: {selected_aoi}")

    if selected_aoi.source not in SOURCE_ID_MAPPING:
        logger.error(f"Invalid source: {selected_aoi.source}")
        raise ValueError(
            f"Source: {selected_aoi.source} does not match to any table in PostGIS database."
        )

    return selected_aoi.model_dump()


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
    if aoi_source in {"kba", "wdpa", "landmark"}:
        subregion_limit = SUBREGION_LIMIT_KBA
    else:
        subregion_limit = SUBREGION_LIMIT

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

    This tool queries a spatial database to find location matches for a given place name,
    then uses AI to select the best match based on the user's question context.

    Always translate the place names to English

    This includes:
    - Translating from other languages to English
    - Removing or correcting accented characters (é→e, ã→a, ç→c, etc.)
    - Standardizing to the most common English spelling

    Translation examples:
    - "Odémire" → "Odemira"
    - "São Paulo" → "Sao Paulo"
    - "México" → "Mexico"
    - "Köln" → "Cologne"
    - "Bern, Schweiz" → "Bern, Switzerland"
    - "Lisboa em Portugal" → "Lisbon, Portugal"

    Keep pairs of places together in one place name if they belong to the same place deonmination.
    For example, "Lisbon in Portugal" -> "Lisbon, Portugal", do not separate them into "Lisbon" and "Portugal".

    Args:
        question: User's question providing context for selecting the most relevant location
        places: Names of the places or areas to find in the spatial database, expand any abbreviations, translate to English if necessary
        subregion: Specific subregion type to filter results by (optional). Must be one of: "country", "state", "district", "municipality", "locality", "neighbourhood", "kba", "wdpa", or "landmark".
    """
    logger.info(f"PICK-AOI-TOOL: places: '{places}', subregion: '{subregion}'")

    all_results = await asyncio.gather(
        *[query_aoi_database(place, RESULT_LIMIT) for place in places]
    )

    result_csvs = [result.to_csv(index=False) for result in all_results]

    selected_aois = await asyncio.gather(
        *[select_best_aoi(question, result_csv) for result_csv in result_csvs]
    )

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

    tool_message = ""
    for selected_aoi in final_aois:
        selected_aoi[
            SOURCE_ID_MAPPING[selected_aoi["source"]]["id_column"]
        ] = selected_aoi["src_id"]
        tool_message += f"\nSelected AOI: {selected_aoi['name']}, type: {selected_aoi['subtype']}, source: {selected_aoi['source']}, src_id: {selected_aoi['src_id']}"

    logger.debug(f"Pick AOI tool message: {tool_message}")

    selection_name = ", ".join(match_names)
    if subregion:
        selection_name = f"{subregion.capitalize()}s in {selection_name}"

    return Command(
        update={
            "aoi_selection": {
                "name": selection_name,
                "aois": final_aois,
            },
            "aoi": final_aois[0],
            "subtype": final_aois[0]["subtype"],
            "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
        },
    )
