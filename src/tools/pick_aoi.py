import json
from typing import Annotated, Literal, Optional

import duckdb
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.tools.utils.db_connection import get_db_connection
from src.utils.llms import SONNET
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

RESULT_LIMIT = 10

# Optimized table paths (without geometry)
GADM_TABLE = "data/geocode/exports/gadm_no_geom.parquet"
KBA_TABLE = "data/geocode/exports/kba_no_geom.parquet"
LANDMARK_TABLE = "data/geocode/exports/landmark_no_geom.parquet"
WDPA_TABLE = "data/geocode/exports/wdpa_no_geom.parquet"

# Separate geometry table
GEOMETRIES_TABLE = "data/geocode/exports/geometries.parquet"


def query_aoi_database(
    connection: duckdb.DuckDBPyConnection,
    place_name: str,
    result_limit: int = 10,
):
    """Query the Overture database for location information.

    Args:
        connection: DuckDB connection object
        place_name: Name of the place to search for
        result_limit: Maximum number of results to return

    Returns:
        DataFrame containing location information
    """
    sql_query = f"""
        SELECT
            *,
            jaro_winkler_similarity(LOWER(name), LOWER('{place_name}')) AS similarity_score
        FROM gadm_plus
        ORDER BY similarity_score DESC
        LIMIT {result_limit}
    """
    logger.debug(f"Executing AOI query: {sql_query}")
    query_results = connection.sql(sql_query)
    logger.debug(f"AOI query results: {query_results.df()}")
    return query_results.df()


def query_subregion_database(
    connection, subregion_name: str, source: str, src_id: int
):
    """Query the right table in basemaps database for subregions based on the selected AOI.

    Args:
        connection: DuckDB connection object
        subregion_name: Name of the subregion to search for
        source: Source of the selected AOI
        src_id: id of the selected AOI in source table: gadm_id, kba_id, landmark_id, wdpa_id

    Returns:
        list of subregions
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
        case "kba":
            table_name = KBA_TABLE
        case "wdpa":
            table_name = WDPA_TABLE
        case "landmark":
            table_name = LANDMARK_TABLE
        case _:
            logger.error(f"Invalid subregion: {subregion_name}")
            raise ValueError(
                f"Subregion: {subregion_name} does not match to any table in basemaps database."
            )

    # Get the appropriate ID column name based on subregion type
    if subregion_name in ["country", "state", "district", "municipality", "locality", "neighbourhood"]:
        id_column = "gadm_id"
        source_name = "gadm"
    else:
        id_column = f"{subregion_name}_id"
        source_name = subregion_name
    
    sql_query = f"""
    WITH aoi AS (
        SELECT geometry AS geom
        FROM '{GEOMETRIES_TABLE}'
        WHERE source = '{source}' AND src_id = {src_id}
    ),
    subregion_geometries AS (
        SELECT 
            source,
            src_id,
            geometry
        FROM '{GEOMETRIES_TABLE}'
        WHERE source = '{source_name}'
    )
    SELECT 
        t.*
    FROM '{table_name}' AS t
    CROSS JOIN aoi
    JOIN subregion_geometries sg ON t.{id_column} = sg.src_id
    WHERE ST_Within(sg.geometry, aoi.geom);
    """
    logger.debug(f"Executing subregion query: {sql_query}")
    results = connection.execute(sql_query).df()
    
    # Note: Geometry is not returned - only used for spatial filtering
    logger.debug(f"Found {len(results)} subregions within AOI")
    return results


def get_aoi_geometry(connection: duckdb.DuckDBPyConnection, source: str, src_id: int):
    """Fetch geometry for a specific AOI from the geometry table.
    
    Args:
        connection: DuckDB connection object
        source: Source of the AOI ('gadm', 'kba', 'landmark', 'wdpa')
        src_id: Source-specific ID of the AOI
        
    Returns:
        GeoJSON geometry dict or None if not found
    """
    sql_query = f"""
        SELECT ST_AsGeoJSON(geometry) as geometry
        FROM '{GEOMETRIES_TABLE}'
        WHERE source = '{source}' AND src_id = {src_id}
        LIMIT 1
    """
    
    logger.debug(f"Fetching geometry for {source}:{src_id}")
    
    try:
        result = connection.sql(sql_query).fetchone()
        if result and result[0]:
            return json.loads(result[0])
        else:
            logger.warning(f"No geometry found for {source}:{src_id}")
            return None
    except Exception as e:
        logger.error(f"Failed to fetch geometry for {source}:{src_id}: {e}")
        return None


class AOIIndex(BaseModel):
    """Model for storing the index of the selected location."""

    id: int = Field(
        description="`id` of the location that best matches the user query."
    )
    source: str = Field(description="`source` of the selected location.")
    src_id: int = Field(description="`src_id` of the selected location.")


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
AOI_SELECTION_CHAIN = AOI_SELECTION_PROMPT | SONNET.with_structured_output(
    AOIIndex
)


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
        logger.info(
            f"PICK-AOI-TOOL: place: '{place}', subregion: '{subregion}'"
        )
        # Query the database for place & get top matches using jaro winkler similarity
        db_connection = get_db_connection()
        results = query_aoi_database(db_connection, place, RESULT_LIMIT)

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

        # Fetch metadata from the appropriate table (without geometry)
        match source:
            case "gadm":
                selected_aoi = (
                    db_connection.sql(
                        f"SELECT * FROM '{GADM_TABLE}' WHERE gadm_id = {src_id}"
                    )
                    .df()
                    .iloc[0]
                    .to_dict()
                )
            case "kba":
                selected_aoi = (
                    db_connection.sql(
                        f"SELECT * FROM '{KBA_TABLE}' WHERE kba_id = {src_id}"
                    )
                    .df()
                    .iloc[0]
                    .to_dict()
                )
            case "landmark":
                selected_aoi = (
                    db_connection.sql(
                        f"SELECT * FROM '{LANDMARK_TABLE}' WHERE landmark_id = {src_id}"
                    )
                    .df()
                    .iloc[0]
                    .to_dict()
                )
            case "wdpa":
                selected_aoi = (
                    db_connection.sql(
                        f"SELECT * FROM '{WDPA_TABLE}' WHERE wdpa_id = {src_id}"
                    )
                    .df()
                    .iloc[0]
                    .to_dict()
                )
            case _:
                logger.error(f"Invalid source: {source}")
                raise ValueError(
                    f"Source: {source} does not match to any table in basemaps database."
                )
        
        # Note: Geometry is not included in the frontend response
        # Frontend should fetch geometry via API endpoints when needed for map rendering
        
        if subregion:
            logger.info(f"Querying for subregion: '{subregion}'")
            subregion_aois = query_subregion_database(
                db_connection, subregion, source, src_id
            )
            # Convert to records for frontend (geometry already excluded from query)
            subregion_aois = subregion_aois.to_dict(orient="records")
            logger.info(f"Found {len(subregion_aois)} subregion AOIs")

        tool_message = f"Selected AOI: {selected_aoi['name']}, type: {selected_aoi['subtype']}"
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
                "messages": [
                    ToolMessage(tool_message, tool_call_id=tool_call_id)
                ],
            },
        )
    except Exception as e:
        logger.error(f"Error in pick_aoi tool: {e}")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        str(e), tool_call_id=tool_call_id, status="error"
                    )
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
        "find threats to tigers in Odisha",
        "find threats to tigers in KBAs of Odisha",
        "Show me forest data for congo not drc",
        "What is the deforestation rate in Ontario last year?",
        "I need urgent data on ilegal logging in Borgou!!",
        "How much tree cover has been lost in Sumatera since 2000?",
        "find threats to tigers in Simlipal Park",
        "find deforestation rate in Amazon",
        "find crocodile statistics in Satkosia Gorge",
        "find deforestation rate in PNG",
    ]

    for query in user_queries[:5]:
        for step in agent.stream(
            {"messages": [{"role": "user", "content": query}]},
            stream_mode="values",
        ):
            message = step["messages"][-1]
            if isinstance(message, tuple):
                logger.info(message)
            else:
                message.pretty_print()
