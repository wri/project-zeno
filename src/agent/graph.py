import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    wrap_tool_call,
)
from langchain.messages import ToolMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from src.agent.llms import FALLBACK_MODELS, MODEL
from src.agent.skills import all_skills
from src.agent.state import AgentState
from src.agent.tools import (
    generate_insights,
    get_capabilities,
    inspect_state,
    pick_aoi,
    pick_dataset,
    pull_data,
    read_skill,
    wri_insights,
)
from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def get_prompt(user: Optional[dict] = None) -> str:
    """Generate the prompt with current date. (Ignore user information)"""
    skill_lines = [
        f"- {s.name}: {s.description} (when: {s.when_to_use})"
        for s in all_skills()
        if s.name != "generate-insights-executor"
    ]
    skills_block = "\n".join(skill_lines)
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""You are Global Nature Watch's Geospatial Agent. Call tools one at a time, never in parallel.

Today: {today}

Skills (call read_skill(name) only when its "when" clause matches — usually one skill, not the whole list):
{skills_block}

Request scope:
- Dataset-only (e.g. "pick tcl by driver"): read `pick-dataset`, call `pick_dataset`, stop. No AOI, pull, or insights unless asked.
- AOI-only: read `pick-aoi`, call `pick_aoi`, stop unless the user asked for more.
- Pull-only (e.g. "pull dist alerts in Bern for last 2 weeks"): read `pull-data`, run pick_aoi → pick_dataset → pull_data, then stop. Do not call `generate_insights` unless the user asked for analysis or a chart.
- Full analysis (place + topic → chart/insight): read `analyze` and follow that pipeline (includes `generate_insights`).
- Do not read `analyze` for dataset-only, AOI-only, or pull-only requests.

Tools: pick_aoi, pick_dataset, pull_data, generate_insights, get_capabilities, inspect_state, read_skill, wri_insights
"""


tools = [
    get_capabilities,
    pick_aoi,
    pick_dataset,
    pull_data,
    generate_insights,
    inspect_state,
    read_skill,
    wri_insights,
]

load_dotenv()


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
_checkpointer_pool: Optional[AsyncConnectionPool] = None


async def get_checkpointer_pool() -> AsyncConnectionPool:
    """Get or create the global checkpointer connection pool."""
    global _checkpointer_pool
    if _checkpointer_pool is None:
        _checkpointer_pool = AsyncConnectionPool(
            DATABASE_URL,
            min_size=SharedSettings.db_pool_size,
            max_size=SharedSettings.db_max_overflow
            + SharedSettings.db_pool_size,
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


@wrap_tool_call
async def handle_tool_errors(request, handler):
    try:
        return await handler(request)
    except Exception as e:
        logger.exception("Tool execution failed")
        return ToolMessage(
            content=f"Tool error: {str(e)}",
            tool_call_id=request.tool_call["id"],
        )


def _build_middleware():
    """Build the middleware stack: retry -> fallback -> tool error handling.

    Middleware execution order and interaction:
    1. ModelRetryMiddleware: Retries transient failures (rate limits, timeouts)
       - on_failure="error": Re-raises exception after exhausting retries
       - This allows the exception to propagate to ModelFallbackMiddleware

    2. ModelFallbackMiddleware: Tries alternative models on exceptions
       - Only triggers if an exception is raised (not on error messages)

    3. handle_tool_errors: Catches tool execution errors and returns ToolMessage
       - Final safety net for tool-specific failures
    """
    middleware = [
        ModelRetryMiddleware(
            max_retries=3,
            backoff_factor=2.0,
            initial_delay=1.0,
            on_failure="error",  # Must be "error" to trigger fallback middleware
        ),
    ]
    if FALLBACK_MODELS:
        middleware.append(ModelFallbackMiddleware(*FALLBACK_MODELS))
    middleware.append(handle_tool_errors)
    return middleware


async def fetch_zeno_anonymous(
    user: Optional[dict] = None,
    system_prompt: Optional[str] = None,
) -> CompiledStateGraph:
    """Setup the Zeno agent for anonymous users with the provided tools and prompt."""
    # async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
    # Create the Zeno agent with the provided tools and prompt

    zeno_agent = create_agent(
        model=MODEL,
        tools=tools,
        state_schema=AgentState,
        system_prompt=system_prompt or get_prompt(user),
        middleware=_build_middleware(),
    )
    return zeno_agent


async def fetch_zeno(
    user: Optional[dict] = None,
    system_prompt: Optional[str] = None,
) -> CompiledStateGraph:
    """Setup the Zeno agent with the provided tools and prompt."""

    checkpointer = await fetch_checkpointer()
    zeno_agent = create_agent(
        model=MODEL,
        tools=tools,
        state_schema=AgentState,
        system_prompt=system_prompt or get_prompt(user),
        middleware=_build_middleware(),
        checkpointer=checkpointer,
    )
    return zeno_agent
