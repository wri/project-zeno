from typing import Annotated, Dict, Literal, Optional

import pandas as pd
import structlog
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState, create_react_agent
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.utils.database import get_connection_from_pool
from src.utils.env_loader import load_environment_variables
from src.utils.geocoding_helpers import (
    CUSTOM_AREA_TABLE,
    GADM_TABLE,
    KBA_TABLE,
    LANDMARK_TABLE,
    SOURCE_ID_MAPPING,
    SUBREGION_TO_SUBTYPE_MAPPING,
    WDPA_TABLE,
)
from src.utils.llms import MODEL, SMALL_MODEL
from src.utils.logging_config import get_logger

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
    AOI_SELECTION_CHAIN = AOI_SELECTION_PROMPT | MODEL.with_structured_output(
        AOIIndex
    )

    selected_aoi = await AOI_SELECTION_CHAIN.ainvoke(
        {"candidate_locations": candidate_aois, "user_query": question}
    )
    logger.debug(f"Candidate locations: {candidate_aois}")
    logger.debug(f"Selected AOI: {selected_aoi}")

    return selected_aoi


async def translate_to_english(question, place_name):
    """Translate place name to English if it's in a different language."""

    class Place(BaseModel):
        name: str

    TRANSLATE_TO_ENGLISH_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "user",
                """
                Translate or correct the following place name to its standard English form.
                This includes:
                - Translating from other languages to English
                - Removing or correcting accented characters (é→e, ã→a, ç→c, etc.)
                - Standardizing to the most common English spelling

                Examples:
                - "Odémire" → "Odemira"
                - "São Paulo" → "Sao Paulo"
                - "México" → "Mexico"
                - "Köln" → "Cologne"
                - "Bern, Schweiz" → "Bern, Switzerland"
                - "Lisboa em Portugal" → "Lisbon, Portugal"

                User query:
                {question}

                Place name to translate/correct:
                {place_name}

                Return only the corrected place name, nothing else.
                """,
            )
        ]
    )

    translate_to_english_chain = (
        TRANSLATE_TO_ENGLISH_PROMPT | SMALL_MODEL.with_structured_output(Place)
    )

    english_place_name = await translate_to_english_chain.ainvoke(
        {
            "question": question,
            "place_name": place_name,
        }
    )
    logger.info(f"English place name: {english_place_name.name}")

    return english_place_name.name


@tool("pick_aoi")
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
    state: Annotated[Dict, InjectedState] = {},
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
        # Query the database for place & get top matches using similarity

        # Translate place name to English if it's in a different language
        place = await translate_to_english(question, place)

        # Query the database for place & get top matches using similarity
        results = await query_aoi_database(place, RESULT_LIMIT)

        # Convert results to CSV
        candidate_aois = results.to_csv(
            index=False
        )  # results: id, name, subtype, source, src_id

        # Select the best AOI based on user query
        selected_aoi = await select_best_aoi(question, candidate_aois)
        source = selected_aoi.source
        src_id = selected_aoi.src_id
        name = selected_aoi.name
        subtype = selected_aoi.subtype

        # Check if NAME of selected AOI is an exact match of any of the names in the results, then ask the user for clarification
        short_name = name.split(",")[0]

        # For GADM sources, check for exact name matches from different countries
        if source == "gadm":
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
                        (
                            results.name.str.lower().str.startswith(
                                short_name.lower()
                            )
                        )
                        & (results.source == "gadm")
                    ]

                    candidate_names = all_matches[
                        ["name", "subtype", "src_id"]
                    ].to_dict(orient="records")
                    candidate_names = "\n".join(
                        [
                            f"{candidate['name']} - ({candidate['subtype']}) [{candidate['src_id'].split('.')[0]}]"
                            for candidate in candidate_names
                        ]
                    )
                    return Command(
                        update={
                            "messages": [
                                ToolMessage(
                                    f"I found multiple locations named '{short_name}' in different countries. Please tell me which one you meant:\n\n{candidate_names}\n\nWhich location are you looking for?",
                                    tool_call_id=tool_call_id,
                                    status="success",
                                    response_metadata={
                                        "msg_type": "human_feedback"
                                    },
                                )
                            ],
                        },
                    )

        # todo: this is redundant with the one in helpers.py, consider refactoring
        source_table_map = {
            "gadm": GADM_TABLE,
            "kba": KBA_TABLE,
            "landmark": LANDMARK_TABLE,
            "wdpa": WDPA_TABLE,
            "custom": CUSTOM_AREA_TABLE,
        }

        if source not in source_table_map:
            logger.error(f"Invalid source: {source}")
            raise ValueError(
                f"Source: {source} does not match to any table in PostGIS database."
            )

        if subregion:
            logger.info(f"Querying for subregion: '{subregion}'")
            subregion_aois = await query_subregion_database(
                subregion, source, src_id
            )
            subregion_aois = subregion_aois.to_dict(orient="records")
            logger.info(f"Found {len(subregion_aois)} subregion AOIs")

            # Limit subregions based on source
            if subregion in {"kba", "wdpa", "landmark"}:
                subregion_limit = 25
            else:
                subregion_limit = 50

            # Check if too many subregions found
            if len(subregion_aois) > subregion_limit:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                f"Found {len(subregion_aois)} subregions, which is too many to process efficiently. "
                                f"Please narrow down your search by either:\n"
                                f"1. Being more specific with the AOI selection (choose a smaller area)\n"
                                f"2. Being more specific with the subregion query (e.g., 'kbas' instead of 'areas')\n"
                                f"For optimal performance, please limit results to under 25 subregions for KBA, WDPA, and Indigenous Lands, or under 50 for other area types.",
                                tool_call_id=tool_call_id,
                                status="success",
                                response_metadata={
                                    "msg_type": "human_feedback"
                                },
                            )
                        ],
                    },
                )
        else:
            subregion_aois = []

        tool_message = f"Selected AOI: {name}, type: {subtype}"
        if subregion:
            subregion_aoi_names = [
                subregion_aoi["name"].split(",")[0]
                for subregion_aoi in subregion_aois
            ]
            if len(subregion_aoi_names) > 5:
                displayed_names = subregion_aoi_names[:5]
                remaining = len(subregion_aoi_names) - 5
                tool_message += f"\nSubregion AOIs: {'\n'.join(displayed_names)}\n... ({remaining} more)"
            else:
                tool_message += (
                    f"\nSubregion AOIs: {'\n'.join(subregion_aoi_names)}"
                )

        logger.debug(f"Pick AOI tool message: {tool_message}")
        selected_aoi = selected_aoi.model_dump()
        selected_aoi[SOURCE_ID_MAPPING[source]["id_column"]] = src_id

        logger.info(
            f"Selected AOI: {name}, type: {subtype}, source: {source}, src_id: {src_id}"
        )
        aoi_options = state.get("aoi_options", [])
        if aoi_options is None:
            aoi_options = []
        aoi_options.append(
            {
                "aoi": selected_aoi,
                "subregion_aois": subregion_aois,
                "subregion": subregion,
                "subtype": subtype,
            }
        )

        return Command(
            update={
                "aoi": selected_aoi,
                "subregion_aois": subregion_aois if subregion else None,
                "subregion": subregion,
                "aoi_name": name,
                "subtype": subtype,
                "aoi_options": aoi_options,
                # Update the message history
                "messages": [
                    ToolMessage(tool_message, tool_call_id=tool_call_id)
                ],
            },
        )
    except Exception as e:
        logger.exception(f"Error in pick_aoi tool: {e}")
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
        MODEL,
        tools=[pick_aoi],
        prompt="""You are a Geo Agent that can ONLY HELP PICK an AOI using the `pick_aoi` tool.
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
