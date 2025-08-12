import os
from typing import Annotated, Literal, Optional

import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.utils.env_loader import load_environment_variables
from src.utils.geocoding_helpers import (
    GADM_TABLE,
    KBA_TABLE,
    LANDMARK_TABLE,
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
    WDPA_TABLE,
)
from src.utils.llms import SONNET
from src.utils.logging_config import get_logger
from src.utils.database import get_async_engine
from src.utils.config import APISettings

RESULT_LIMIT = 10


load_environment_variables()
logger = get_logger(__name__)


# def get_postgis_connection():
#     """Get PostGIS database connection."""
#     database_url = os.environ["DATABASE_URL"].replace(
#         "postgresql+asyncpg://", "postgresql+psycopg2://"
#     )
#     return create_engine(database_url)


async def query_aoi_database(
    engine,
    place_name: str,
    result_limit: int = 10,
):
    """Query the PostGIS database for location information.

    Args:
        engine: SQLAlchemy engine object
        place_name: Name of the place to search for
        result_limit: Maximum number of results to return

    Returns:
        DataFrame containing location information
    """
    async with engine.connect() as conn:
        # Enable pg_trgm extension for similarity function
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.execute(text("SET pg_trgm.similarity_threshold = 0.2;"))
        await conn.commit()

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

        # Build the query based on existing tables
        union_parts = []

        if "gadm" in existing_tables:
            union_parts.append(
                f"""
                SELECT gadm_id AS src_id,
                    name, subtype, 'gadm' as source
                FROM {GADM_TABLE}
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
                params={"place_name": place_name, "limit_val": result_limit},
            )

        query_results = await conn.run_sync(_read)

    logger.debug(f"AOI query results: {query_results}")
    return query_results


async def query_subregion_database(
    engine, subregion_name: str, source: str, src_id: int
):
    """Query the right table in PostGIS database for subregions based on the selected AOI.

    Args:
        engine: SQLAlchemy engine object
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

    async with engine.connect() as conn:

        def _read(sync_conn):
            return pd.read_sql(
                text(sql_query),
                sync_conn,
                params={"src_id": src_id, "subtype": subtype},
            )

        results = await conn.run_sync(_read)

    return results


class AOIIndex(BaseModel):
    """Model for storing the index of the selected location."""

    id: int = Field(
        description="`id` of the location that best matches the user query."
    )
    source: str = Field(description="`source` of the selected location.")
    src_id: str = Field(description="`src_id` of the selected location.")


# Prompt template for selecting the best location match based on user query
AOI_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "user",
            """
            Based on the query, return the ID of the best location match.
            When there is a tie, give preference to country > state > district > municipality > locality.

            {candidate_locations}

            Query:

            {user_query}
            """,
        )
    ]
)

# Chain for selecting the best location match
AOI_SELECTION_CHAIN = AOI_SELECTION_PROMPT | SONNET.with_structured_output(AOIIndex)


@tool("pick-aoi")
async def pick_aoi(
    question: str,
    place: str,
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

    Args:
        question: User's question providing context for selecting the most relevant location
        place: Name of the place or area to find in the spatial database, expand any abbreviations
        subregion: Specific subregion type to filter results by (optional). Must be one of: "country", "state", "district", "municipality", "locality", "neighbourhood", "kba", "wdpa", or "landmark".
    """
    try:
        logger.info(f"PICK-AOI-TOOL: place: '{place}', subregion: '{subregion}'")
        # Query the database for place & get top matches using similarity

        # TODO: we may need to replace `asyncpg` with `psycopg` in the
        # database URL (this was how the tool was originally setup)
        engine = await get_async_engine(db_url=APISettings.database_url)

        results = await query_aoi_database(engine, place, RESULT_LIMIT)

        candidate_aois = results.to_csv(
            index=False
        )  # results: id, name, subtype, source, src_id

        # Select the best AOI based on user query
        selected_aoi = await AOI_SELECTION_CHAIN.ainvoke(
            {"candidate_locations": candidate_aois, "user_query": question}
        )
        selected_aoi_id = selected_aoi.id
        source = selected_aoi.source
        src_id = selected_aoi.src_id

        logger.debug(
            f"Selected AOI id: {selected_aoi_id}, source: '{source}', src_id: {src_id}"
        )

        # todo: this is redundant with the one in helpers.py, consider refactoring
        source_table_map = {
            "gadm": GADM_TABLE,
            "kba": KBA_TABLE,
            "landmark": LANDMARK_TABLE,
            "wdpa": WDPA_TABLE,
        }

        if source not in source_table_map:
            logger.error(f"Invalid source: {source}")
            raise ValueError(
                f"Source: {source} does not match to any table in PostGIS database."
            )

        id_column = SOURCE_ID_MAPPING[source]["id_column"]
        source_table = source_table_map[source]

        sql_query = f"""
            SELECT name, subtype, "{id_column}" as src_id
            FROM {source_table}
            WHERE "{id_column}" = :src_id
        """

        async with engine.connect() as conn:

            def _read(sync_conn):
                return pd.read_sql(
                    text(sql_query), sync_conn, params={"src_id": src_id}
                )

            selected_aoi_df = await conn.run_sync(_read)

        if selected_aoi_df.empty:
            raise ValueError(f"No AOI found with {id_column} = {src_id}")

        selected_aoi = selected_aoi_df.iloc[0].to_dict()
        selected_aoi[SOURCE_ID_MAPPING[source]["id_column"]] = src_id
        selected_aoi["source"] = source

        if subregion:
            logger.info(f"Querying for subregion: '{subregion}'")
            subregion_aois = await query_subregion_database(
                engine, subregion, source, src_id
            )
            subregion_aois = subregion_aois.to_dict(orient="records")
            logger.info(f"Found {len(subregion_aois)} subregion AOIs")

        tool_message = (
            f"Selected AOI: {selected_aoi['name']}, type: {selected_aoi['subtype']}"
        )
        if subregion:
            tool_message += f"\nSubregion AOIs: {len(subregion_aois)}"

        logger.debug(f"Pick AOI tool message: {tool_message}")

        return Command(
            update={
                "aoi": selected_aoi,
                "subregion_aois": subregion_aois if subregion else None,
                "subregion": subregion,
                "aoi_name": selected_aoi["name"],
                "subtype": selected_aoi["subtype"],
                # Update the message history
                "messages": [ToolMessage(tool_message, tool_call_id=tool_call_id)],
            },
        )
    except Exception as e:
        logger.exception(f"Error in pick_aoi tool: {e}")
        return Command(
            update={
                "messages": [
                    ToolMessage(str(e), tool_call_id=tool_call_id, status="error")
                ],
            },
        )


if __name__ == "__main__":
    agent = create_react_agent(
        SONNET,
        tools=[pick_aoi],
        prompt="""You are a Geo Agent that can ONLY HELP PICK an AOI using the `pick-aoi` tool.
        Pick the best AOI based on the user query. You DONT need to answer the user query, just pick the best AOI.""",
    )

    user_queries = [
        "find threats to tigers in kbas of Odisha",
        "Show me forest data for congo not drc",
        "What is the deforestation rate in Ontario last year?",
        "I need urgent data on ilegal logging in Borgou!!",
        "How much tree cover has been lost in Sumatera since 2000?",
        "find threats to tigers in Simlipal Park",
        "find deforestation rate in Amazon",
        "find crocodile statistics in Satkosia Gorge",
        "find deforestation rate in PNG",
    ]

    for query in user_queries[:1]:
        for step in agent.stream(
            {"messages": [{"role": "user", "content": query}]},
            stream_mode="values",
        ):
            message = step["messages"][-1]
            if isinstance(message, tuple):
                logger.info(message)
            else:
                message.pretty_print()
