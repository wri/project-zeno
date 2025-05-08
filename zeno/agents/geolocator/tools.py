from typing import Annotated

import duckdb
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_openai import ChatOpenAI
from langgraph.types import Command
from pydantic import BaseModel, Field

# Initialize language models with zero temperature for deterministic outputs
CLAUDE_MODEL = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0) 
GPT_MODEL = ChatOpenAI(model="gpt-4o", temperature=0)


def create_database_connection(database_path: str):
    """Create and configure a DuckDB connection with necessary extensions.
    
    Args:
        database_path: Path to the DuckDB database file
        
    Returns:
        Configured DuckDB connection
    """
    connection = duckdb.connect(database_path)
    connection.load_extension("spatial")
    connection.load_extension("httpfs")
    return connection


def query_location_database(connection, location_name: str, result_limit: int = 5):
    """Query the Overture database for location information.
    
    Args:
        connection: DuckDB connection object
        location_name: Name of the location to search for
        result_limit: Maximum number of results to return
        
    Returns:
        DataFrame containing location information
    """
    sql_query = f"""
        WITH 
        ranked AS (
            SELECT
                d.*,
                jaro_winkler_similarity(d.names.primary, '{location_name}') AS similarity_score
            FROM division d
            WHERE d.subtype IN ('region', 'county', 'country')
            ORDER BY similarity_score DESC
            LIMIT {result_limit}
        )
        SELECT 
            r.id, r.similarity_score, r.country, r.subtype, r.region,
            da.id as area_id,
            ST_AsText(r.geometry) as point_geometry,
            ST_AsText(da.geometry) as area_geometry,
            r.names.primary as location_name,
            da.names.primary as area_name
        FROM ranked AS r
        LEFT JOIN division_area AS da
                ON r.id == da.division_id
        ORDER BY similarity_score DESC
        """
    query_results = connection.sql(sql_query)
    print("SQL results: ")
    print(query_results)
    return query_results.df()


class LocationIndex(BaseModel):
    """Model for storing the index of the selected location."""
    index: int = Field(description="Index of the location that best matches the user query.")


# Prompt template for selecting the best location match based on user query
LOCATION_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
            Based on the user query, return the `index` of the best location match:

            {candidate_locations}

            Here's the user query:

            {user_query}
            """,
        )
    ]
)

# Chain for selecting the best location match
LOCATION_SELECTION_CHAIN = LOCATION_SELECTION_PROMPT | GPT_MODEL.with_structured_output(LocationIndex)


@tool
def geocode(question: str, place: str, database: str = "overture", tool_call_id: Annotated[str, InjectedToolCallId] = None) -> Command:
    """Get geometry (point, polygon) of a place.

    Args:
        question: User's question formatted into a clearer version, fixing any typos or abbreviations
        place: Name of the place to geocode
        database: Optional, database to search, defaults to: overture
        
    Returns:
        Command with location information and updated message history
    """
    if database == "kba":
        # Placeholder for future KBA database implementation
        pass
    else:   
        # Make connection to the database
        database_connection = create_database_connection("data/geolocator/overture.ddb")
        # Query the database for place
        location_results = query_location_database(database_connection, place)
        database_connection.close()

    # Extract relevant location information for selection
    candidate_locations = location_results[["id", "location_name", "subtype", "region"]].to_dict(orient="records") 

    # Select the best location match based on user query
    selected_location_index = LOCATION_SELECTION_CHAIN.invoke({
        "candidate_locations": candidate_locations,
        "user_query": question
    })

    # Get the full details of the selected location
    selected_location = location_results.iloc[selected_location_index.index].to_dict()

    return Command(
        update={
            "location": selected_location,
            "place": selected_location["location_name"],
            # Update the message history
            "messages": [
                ToolMessage(
                    f"Successfully geocoded the place {selected_location['location_name']}, {selected_location['region']} and saved inside state.", 
                    tool_call_id=tool_call_id
                )
            ],
        },
    )