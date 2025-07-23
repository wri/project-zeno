import json
import os
from typing import Annotated, Literal, Optional

import requests
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.utils.llms import SONNET
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

RESULT_LIMIT = 10

# AOI Service configuration
GEOCODING_SERVICE_URL = os.getenv("GEOCODING_SERVICE_URL", "http://localhost:8081")


def query_aoi_database(
    place_name: str,
    result_limit: int = 10,
):
    """Query the AOI service for location information.

    Args:
        place_name: Name of the place to search for
        result_limit: Maximum number of results to return

    Returns:
        DataFrame containing location information
    """
    try:
        response = requests.post(
            f"{GEOCODING_SERVICE_URL}/aoi/search",
            json={"place_name": place_name, "result_limit": result_limit},
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        results = data["results"]

        # Convert to DataFrame to maintain compatibility
        import pandas as pd

        results_df = pd.DataFrame(results)

        logger.debug(f"AOI query results: {results_df}")
        return results_df

    except requests.RequestException as e:
        logger.error(f"Failed to query AOI service: {e}")
        raise Exception(f"AOI service request failed: {e}")


def query_subregion_database(subregion_name: str, source: str, src_id: int):
    """Query the AOI service for subregions based on the selected AOI.

    Args:
        subregion_name: Name of the subregion to search for
        source: Source of the selected AOI
        src_id: id of the selected AOI in source table: gadm_id, kba_id, landmark_id, wdpa_id

    Returns:
        DataFrame containing subregions
    """
    try:
        response = requests.post(
            f"{GEOCODING_SERVICE_URL}/aoi/subregions",
            json={"subregion_name": subregion_name, "source": source, "src_id": src_id},
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        results = data["results"]

        # Convert to DataFrame to maintain compatibility
        import pandas as pd

        results_df = pd.DataFrame(results)

        logger.debug(f"Subregion query results: {results_df}")
        return results_df

    except requests.RequestException as e:
        logger.error(f"Failed to query subregion from AOI service: {e}")
        raise Exception(f"AOI service subregion request failed: {e}")


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
        # Query the AOI service for place & get top matches using jaro winkler similarity
        results = query_aoi_database(place, RESULT_LIMIT)

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

        # Get the selected AOI details from the service
        try:
            response = requests.post(
                f"{GEOCODING_SERVICE_URL}/aoi/by-id",
                json={"source": source, "src_id": src_id},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            selected_aoi = data["result"]
        except requests.RequestException as e:
            logger.error(f"Failed to get AOI by ID from service: {e}")
            raise Exception(f"AOI service get-by-id request failed: {e}")

        # Geometry parsing is now handled by the AOI service
        logger.debug(
            f"Selected AOI geometry: {selected_aoi.get('geometry', 'No geometry')}"
        )

        if subregion:
            logger.info(f"Querying for subregion: '{subregion}'")
            subregion_results = query_subregion_database(subregion, source, src_id)
            subregion_aois = subregion_results.to_dict(orient="records")
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
