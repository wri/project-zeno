import json
from typing import Annotated, Literal, Optional
import os
import pandas as pd

from sqlalchemy import create_engine, text
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.utils.env_loader import load_environment_variables
from src.utils.llms import SONNET
from src.utils.logging_config import get_logger
from src.utils.geocoding_helpers import (
    SOURCE_ID_MAPPING,
    GADM_TABLE,
    KBA_TABLE,
    LANDMARK_TABLE,
    WDPA_TABLE,
    SUBREGION_TO_SUBTYPE_MAPPING,
)


RESULT_LIMIT = 10


load_environment_variables()
logger = get_logger(__name__)


def get_postgis_connection():
    """Get PostGIS database connection."""
    database_url = os.environ["DATABASE_URL"]
    return create_engine(database_url)


def query_aoi_database(
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
    with engine.connect() as conn:
        # Enable pg_trgm extension for similarity function
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        conn.execute(text("SET pg_trgm.similarity_threshold = 0.2;"))
        conn.commit()

        # Check which tables exist first
        existing_tables = []

        # Check GADM table
        try:
            conn.execute(text(f"SELECT 1 FROM {GADM_TABLE} LIMIT 1"))
            existing_tables.append("gadm")
        except Exception:
            logger.warning(f"Table {GADM_TABLE} does not exist")
            conn.rollback()

        # Check KBA table
        try:
            conn.execute(text(f"SELECT 1 FROM {KBA_TABLE} LIMIT 1"))
            existing_tables.append("kba")
        except Exception:
            logger.warning(f"Table {KBA_TABLE} does not exist")
            conn.rollback()

        # Check Landmark table
        try:
            conn.execute(text(f"SELECT 1 FROM {LANDMARK_TABLE} LIMIT 1"))
            existing_tables.append("landmark")
        except Exception:
            logger.warning(f"Table {LANDMARK_TABLE} does not exist")
            conn.rollback()

        # Check WDPA table
        try:
            conn.execute(text(f"SELECT 1 FROM {WDPA_TABLE} LIMIT 1"))
            existing_tables.append("wdpa")
        except Exception:
            logger.warning(f"Table {WDPA_TABLE} does not exist")
            conn.rollback()

        # Build the query based on existing tables
        union_parts = []
        row_offset = 0

        if "gadm" in existing_tables:
            union_parts.append(
                f"""
                SELECT gadm_id AS src_id,
                    name, subtype, 'gadm' as source,
                    ROW_NUMBER() OVER() + {row_offset} as id
                FROM {GADM_TABLE}
            """
            )
            # Get count for offset calculation
            gadm_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {GADM_TABLE}")
            ).scalar()
            row_offset += gadm_count

        if "kba" in existing_tables:
            src_id = SOURCE_ID_MAPPING["kba"]["id_column"]
            union_parts.append(
                f"""
                SELECT CAST({src_id} as TEXT) as src_id,
                       name,
                       subtype,
                       'kba' as source,
                       ROW_NUMBER() OVER() + {row_offset} as id
                FROM {KBA_TABLE}
            """
            )
            # Get count for offset calculation
            kba_count = conn.execute(text(f"SELECT COUNT(*) FROM {KBA_TABLE}")).scalar()
            row_offset += kba_count

        if "landmark" in existing_tables:
            src_id = SOURCE_ID_MAPPING["landmark"]["id_column"]
            union_parts.append(
                f"""
                SELECT CAST({src_id} as TEXT) as src_id,
                       name,
                       subtype,
                       'landmark' as source,
                       ROW_NUMBER() OVER() + {row_offset} as id
                FROM {LANDMARK_TABLE}
            """
            )
            # Get count for offset calculation
            landmark_count = conn.execute(
                text(f"SELECT COUNT(*) FROM {LANDMARK_TABLE}")
            ).scalar()
            row_offset += landmark_count

        if "wdpa" in existing_tables:
            src_id = SOURCE_ID_MAPPING["wdpa"]["id_column"]
            union_parts.append(
                f"""
                SELECT CAST({src_id} as TEXT) as src_id,
                       name,
                       subtype,
                       'wdpa' as source,
                       ROW_NUMBER() OVER() + {row_offset} as id
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

        query_results = pd.read_sql(
            text(sql_query),
            conn,
            params={"place_name": place_name, "limit_val": result_limit},
        )

    logger.debug(f"AOI query results: {query_results}")
    return query_results


def query_subregion_database(engine, subregion_name: str, source: str, src_id: int):
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
        case "kba":
            table_name = KBA_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["kba"]
        case "wdpa":
            table_name = WDPA_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["wdpa"]
        case "landmark":
            table_name = LANDMARK_TABLE
            subtype = SUBREGION_TO_SUBTYPE_MAPPING["landmark"]
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
    SELECT t.*, ST_AsGeoJSON(t.geometry) as geometry_json
    FROM {table_name} AS t, aoi
    WHERE t.subtype = :subtype
    AND ST_Within(t.geometry, aoi.geom)
    """
    logger.debug(f"Executing subregion query: {sql_query}")

    with engine.connect() as conn:
        results = pd.read_sql(
            text(sql_query), conn, params={"src_id": src_id, "subtype": subtype}
        )

    # Parse GeoJSON strings in the results
    if not results.empty and "geometry_json" in results.columns:
        for idx, row in results.iterrows():
            if row["geometry_json"] is not None:
                try:
                    results.at[idx, "geometry"] = json.loads(row["geometry_json"])
                except json.JSONDecodeError as e:
                    logger.error(
                        f"Failed to parse GeoJSON for subregion {row.get('name', 'Unknown')}: {e}"
                    )
                    results.at[idx, "geometry"] = None
        # Drop the geometry_json column as we now have parsed geometry
        results = results.drop(columns=["geometry_json"])

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
def pick_aoi(
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
        engine = get_postgis_connection()
        results = query_aoi_database(engine, place, RESULT_LIMIT)

        candidate_aois = results.to_csv(
            index=False
        )  # results: id, name, subtype, source, src_id

        # Select the best AOI based on user query
        selected_aoi = AOI_SELECTION_CHAIN.invoke(
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
            SELECT name, subtype, ST_AsGeoJSON(geometry) as geometry_json, "{id_column}" as src_id
            FROM {source_table}
            WHERE "{id_column}" = :src_id
        """

        with engine.connect() as conn:
            selected_aoi_df = pd.read_sql(
                text(sql_query), conn, params={"src_id": src_id}
            )

        if selected_aoi_df.empty:
            raise ValueError(f"No AOI found with {id_column} = {src_id}")

        selected_aoi = selected_aoi_df.iloc[0].to_dict()
        selected_aoi[SOURCE_ID_MAPPING[source]["id_column"]] = src_id

        # Parse the GeoJSON string into a Python dictionary
        if (
            "geometry_json" in selected_aoi
            and selected_aoi["geometry_json"] is not None
        ):
            try:
                selected_aoi["geometry"] = json.loads(selected_aoi["geometry_json"])
                logger.debug(
                    f"Parsed GeoJSON geometry for AOI: {selected_aoi.get('name', 'Unknown')}"
                )
            except json.JSONDecodeError as e:
                logger.error(
                    f"Failed to parse GeoJSON for AOI {selected_aoi.get('name', 'Unknown')}: {e}"
                )
                selected_aoi["geometry"] = None
            # Remove the geometry_json column as we now have parsed geometry
            del selected_aoi["geometry_json"]
        else:
            logger.warning(
                f"No geometry found for AOI: {selected_aoi.get('name', 'Unknown')}"
            )

        if subregion:
            logger.info(f"Querying for subregion: '{subregion}'")
            subregion_aois = query_subregion_database(engine, subregion, source, src_id)
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
