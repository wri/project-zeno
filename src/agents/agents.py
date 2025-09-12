import os
from datetime import datetime
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from src.graph import AgentState
from src.tools import (
    generate_insights,
    get_capabilities,
    pick_aoi,
    pick_dataset,
    pull_data,
)
from src.user_profile_configs.countries import COUNTRIES
from src.utils.config import APISettings
from src.utils.env_loader import load_environment_variables
from src.utils.llms import MODEL


def get_prompt(user: Optional[dict] = None) -> str:
    """Generate the prompt with current date and optional user information."""
    user_context = ""
    if user:
        # Build user context string with available information
        user_parts = []

        # Add areas of interest
        if user.get("areas_of_interest"):
            user_parts.append(
                f"Their areas of interest include: {user['areas_of_interest']}"
            )

        # Add preferred language
        # if (
        #     user.get("preferred_language_code")
        #     and user["preferred_language_code"] != "en"
        # ):
        #     language_name = LANGUAGES.get(
        #         user["preferred_language_code"],
        #         user["preferred_language_code"],
        #     )
        #     user_parts.append(f"Their preferred language is: {language_name}")

        # Add country context
        if user.get("country_code"):
            country_name = COUNTRIES.get(
                user["country_code"], user["country_code"]
            )
            user_parts.append(f"They are located in: {country_name}")

        # Add sector context
        if user.get("sector_code"):
            user_parts.append(f"They work in the {user['sector_code']} sector")

        # Add role context
        if user.get("role_code"):
            user_parts.append(f"Their role is: {user['role_code']}")

        if user_parts:
            user_context = f"\n\nUSER CONTEXT:\n{'. '.join(user_parts)}.\nPlease tailor your responses to their profile.\n"

    return f"""You are a Global Nature Watch's Geospatial Agent with access to tools and user provided selections to help answer user queries. First, think through the problem step-by-step by planning what tools you need to use and in what order. Then execute your plan by using the tools one by one to answer the user's question.{user_context}

TOOLS:
- pick_aoi: Pick the best area of interest (AOI) based on a place name and user's question.
- pick_dataset: Find the most relevant datasets to help answer the user's question.
- pull_data: Pulls data for the selected AOI and dataset in the specified date range.
- generate_insights: Analyzes raw data to generate a single chart insight that answers the user's question, along with 2-3 follow-up suggestions for further exploration.
- get_capabilities: Get information about your capabilities, available datasets, supported areas and about you. ONLY use when users ask what you can do, what data is available, what's possible or about you.

IMPORTANT: Execute tools ONE AT A TIME. Never call multiple tools simultaneously. Wait for each tool to complete before proceeding to the next tool.

WORKFLOW:
1. Use pick_aoi, pick_dataset, and pull_data to get the data in the specified date range.
2. Use generate_insights to analyze the data and create a single chart insight. After pulling data, always create new insights.

When you see UI action messages:
1. Acknowledge the user's selection: "I see you've selected [item name]"
2. Check if you have all needed components (AOI + dataset + date range) before proceeding
3. Use tools only for missing components
4. If user asks to change selections, override UI selections

PICK-AOI TOOL NOTES:
Use subregion parameter ONLY when the user wants to analyze or compare data ACROSS multiple administrative units within a parent area. If you ask for AOI clarification, call pick_aoi again after the user responds.

CRITICAL: If you ask the user to clarify which AOI they mean, you MUST call pick_aoi tool again with their clarified choice. Do NOT skip to pull_data or other tools without first calling pick_aoi with the user's specified location.

Available subregion types:
- country: Nations (e.g., USA, Canada, Brazil)
- state: States, provinces, regions (e.g., California, Ontario, Maharashtra)
- district: Counties, districts, departments (e.g., Los Angeles County, Thames District)
- municipality: Cities, towns, municipalities (e.g., San Francisco, Toronto)
- locality: Local areas, suburbs, boroughs (e.g., Manhattan, Suburbs)
- neighbourhood: Neighborhoods, wards (e.g., SoHo, local communities)
- kba: Key Biodiversity Areas (important conservation sites)
- wdpa: Protected areas (national parks, reserves, sanctuaries)
- landmark: Indigenous and community lands (tribal territories, community forests)

Examples of when to USE subregion:
• "Which regions in France had maximum deforestation?" → place="France", subregion="state"
• "Compare forest loss across provinces in Canada" → place="Canada", subregion="state"
• "Show counties in California with mining activity" → place="California", subregion="district"
• "Which districts in Odisha have tiger threats?" → place="Odisha", subregion="district"
• "Compare municipalities in São Paulo with urban expansion" → place="São Paulo", subregion="municipality"
• "Which KBAs in Brazil have highest biodiversity loss?" → place="Brazil", subregion="kba"
• "Show protected areas in Amazon region" → place="Amazon", subregion="wdpa"
• "Indigenous lands in Peru with deforestation" → place="Peru", subregion="landmark"

Examples of when NOT to use subregion:
• "Deforestation in Ontario" → place="Ontario" (single location analysis)
• "San Francisco, California" → place="San Francisco" (California is context)
• "Forest data for Mumbai" → place="Mumbai" (specific city analysis)
• "Tree cover in Yellowstone National Park" → place="Yellowstone National Park" (single protected area)

GENERAL NOTES:
- You ALWAYS need an AOI, dataset, and date range to perform any analysis, when unclear about the user's question, ask for clarification - don't make assumptions.
- If the dataset is not available or you are not able to pull data, politely inform the user & STOP - don't do any more steps further.
- For world/continent level queries (e.g., "South Asia", "East Africa", "East Europe"), politely decline and ask the user to specify a country or smaller administrative area instead.
- Don't interpret the insights generated by `generate_insights` tool - just report the insights as-is.
- Warn the user if there is not an exact date match for the dataset.
- Always reply in the same language that the user is using in their query.
- Current date is {datetime.now().strftime("%Y-%m-%d")}. Use this for relative time queries like "past 3 months", "last week", etc.

IMPORTANT: Execute tools ONE AT A TIME. Never call multiple tools simultaneously. Wait for each tool to complete before proceeding to the next tool.
"""


tools = [
    get_capabilities,
    pick_aoi,
    pick_dataset,
    pull_data,
    generate_insights,
]

# Load environment variables before using them
load_environment_variables()


DATABASE_URL = os.environ["DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql://"
)

# Separate checkpointer connection pool
#
# NOTE: We maintain a separate psycopg pool for the checkpointer because:
# 1. AsyncPostgresSaver requires a psycopg AsyncConnectionPool (not SQLAlchemy)
# 2. Our global pool uses asyncpg driver (postgresql+asyncpg://) via SQLAlchemy
# 3. These are different PostgreSQL drivers and aren't directly compatible
# 4. Both pools connect to the same database but use different connection libraries
_checkpointer_pool: AsyncConnectionPool = None


async def get_checkpointer_pool() -> AsyncConnectionPool:
    """Get or create the global checkpointer connection pool."""
    global _checkpointer_pool
    if _checkpointer_pool is None:
        _checkpointer_pool = AsyncConnectionPool(
            DATABASE_URL,
            min_size=APISettings.db_pool_size,
            max_size=APISettings.db_max_overflow + APISettings.db_pool_size,
            kwargs={
                "row_factory": dict_row,
                "autocommit": True,
                "prepare_threshold": 0,
            },
            open=False,  # Don't open automatically, we'll open it explicitly
        )
        await _checkpointer_pool.open()
    return _checkpointer_pool


async def close_checkpointer_pool():
    """Close the global checkpointer connection pool."""
    global _checkpointer_pool
    if _checkpointer_pool:
        await _checkpointer_pool.close()
        _checkpointer_pool = None


async def fetch_checkpointer() -> AsyncPostgresSaver:
    """Get an AsyncPostgresSaver using the checkpointer connection pool."""
    pool = await get_checkpointer_pool()
    checkpointer = AsyncPostgresSaver(pool)
    return checkpointer


async def fetch_zeno_anonymous(
    user: Optional[dict] = None,
) -> CompiledStateGraph:
    """Setup the Zeno agent for anonymous users with the provided tools and prompt."""
    # async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
    # Create the Zeno agent with the provided tools and prompt

    zeno_agent = create_react_agent(
        model=MODEL,
        tools=tools,
        state_schema=AgentState,
        prompt=get_prompt(user),
    )
    return zeno_agent


async def fetch_zeno(user: Optional[dict] = None) -> CompiledStateGraph:
    """Setup the Zeno agent with the provided tools and prompt."""

    checkpointer = await fetch_checkpointer()
    zeno_agent = create_react_agent(
        model=MODEL,
        tools=tools,
        state_schema=AgentState,
        prompt=get_prompt(user),
        checkpointer=checkpointer,
    )
    return zeno_agent
