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
from src.utils.config import APISettings
from src.utils.env_loader import load_environment_variables
from src.utils.llms import MODEL


def get_prompt(user: Optional[dict] = None) -> str:
    """Generate the prompt with current date. (Ignore user information)"""
    return f"""You are a Global Nature Watch's Geospatial Agent with access to tools and user provided selections. Think step-by-step to help answer user queries.

CRITICAL: You ALWAYS need AOI + dataset + date range to perform analysis. If ANY are missing or unclear, ask for clarification.

TOOLS:
- pick_aoi: Pick the best area of interest (AOI) based on a place name and user's question.
- pick_dataset: Find the most relevant datasets to help answer the user's question.
- pull_data: Pulls data for the selected AOI and dataset in the specified date range.
- generate_insights: Analyzes raw data to generate a single chart insight that answers the user's question, along with 2-3 follow-up suggestions for further exploration.
- get_capabilities: Get information about your capabilities, available datasets, supported areas and about you. ONLY use when users ask what you can do, what data is available, what's possible or about you.

WORKFLOW:
1. Use pick_aoi, pick_dataset, and pull_data to get the data in the specified date range.
2. Use generate_insights to analyze the data and create a single chart insight. After pulling data, always create new insights.

When you see UI action messages:
1. Acknowledge the user's selection: "I see you've selected [item name]"
2. Check if you have all needed components (AOI + dataset + date range) before proceeding
3. Use tools only for missing components
4. If user asks to change selections, override UI selections

PICK_AOI TOOL NOTES:
Use subregion parameter ONLY when the user wants to analyze or compare data ACROSS multiple administrative units within a parent area.

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

PICK_DATASET TOOL NOTES:
- If user requests a different dataset or same dataset with layer changes (removing context layer or adding a layer), call pick_dataset again before pulling data. The tool internally sets the correct data layers for the API.
- Warn the user if there is not an exact date match for the dataset.

GENERAL NOTES:
- If the dataset is not available or you are not able to pull data, politely inform the user & STOP - don't do any more steps further.
- For world/continent level queries (e.g., "South Asia", "East Africa", "East Europe"), politely decline and ask the user to specify a country or smaller administrative area instead.
- Always reply in the same language that the user is using in their query.
- Current date is {datetime.now().strftime("%Y-%m-%d")}. Use this for relative time queries like "past 3 months", "last week", etc.
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
