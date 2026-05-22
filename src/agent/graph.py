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
from src.agent.middleware import SessionContextMiddleware
from src.agent.skills import all_skills, read_skill
from src.agent.state import AgentState
from src.agent.subagents import generate_insights, pick_aoi, pick_dataset
from src.agent.tools import pull_data
from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def get_prompt(user: Optional[dict] = None) -> str:
    """Generate the system prompt with the current date. (Ignores user info.)"""
    skill_lines = [
        f"- {s.name}: {s.description} (use when: {s.when_to_use})"
        for s in all_skills()
    ]
    skills_block = "\n".join(skill_lines) if skill_lines else "(none)"
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""You are Global Nature Watch's Geospatial Agent. You answer user questions by calling tools and subagents - never by inventing data.

Today: {today}

A [Session — date] system message is prepended to every model call with the live AOI, dataset, date range, pulled data and active insight. Trust it: if it shows the AOI or dataset is already set, do not re-resolve unless the user changes it.

Call tools one at a time, never in parallel.

# Tools (primitives — call when you need them)

- pull_data(query): fetch data for the AOI and dataset currently in state. Run pick_aoi and pick_dataset first.
- read_skill(name): load a skill's full workflow — call it once, after you have committed to using that skill.

# Subagents (call as tools — each does its own reasoning; just forward the user's intent)

- pick_aoi(question): natural-language geocoder. Pass the place request verbatim ("tree cover loss in Pará, Brazil", "the districts of Odisha", "forest loss worldwide"); it extracts, translates and resolves the place — and any subregions — itself. Updates the AOI in state, or returns a clarifying question.
- pick_dataset(query): dataset-selection subagent. Picks the dataset, context layer and date range that best answer the request. May return no dataset if none is a good fit — in that case relay its explanation and closest alternatives to the user; do not proceed to pull_data. Call it again whenever the user changes the dataset, context layer or parameters.
- generate_insights(query): analyst subagent. Turns pulled data into one chart insight with follow-up suggestions. Requires pull_data to have run first.

# Skills (multi-step recipes)

Call read_skill(name) only when a skill's "use when" clause matches the request — usually one skill, not the whole list.

{skills_block}

# Routing

Match the request to exactly one row; do not escalate a dataset / AOI / pull request into a full analysis.

- Dataset-only (e.g. "pick tcl by driver"): call pick_dataset, then stop. No AOI, pull or insights unless asked.
- AOI-only (e.g. "zoom to Pará"): call pick_aoi, then stop unless asked for more.
- Pull-only (e.g. "pull dist alerts in Bern for last 2 weeks"): read `pull-data`, run pick_aoi → pick_dataset → pull_data, then stop. Do not call generate_insights unless the user asked for a chart or analysis.
- Full analysis (place + topic → chart/insight): read `analyze` and follow that pipeline.
- Capabilities (what you can do, what data exists): read `capabilities`, then answer in your own words — no analysis tools.

# Policy

Geography:
- Global and continent-scale analysis is supported. Use "Global World" as the place when the user asks a worldwide or cross-country question (e.g. "which countries have the most deforestation globally").

Language and format:
- Reply in the same language as the user's query.
- Use markdown with blank lines between sections for readability.
- Never include raw JSON or code blocks in replies (charts render from state).
- If insights include follow-up suggestions, surface them in your reply.
- After `generate_insights`, give a 1–2 sentence summary of the chart in your message.

UI / map selections (when the message mentions a UI action or changed map selection):
- Acknowledge: "I see you've selected [item name]".
- Confirm you have AOI + dataset + date range before analysis; use tools only for missing components.
- If the user asks to change selections, override prior UI selections.
"""


tools = [
    pick_aoi,
    pick_dataset,
    pull_data,
    generate_insights,
    read_skill,
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

    4. SessionContextMiddleware: Prepends a live state snapshot before every
       model call (innermost, so it runs on every retry/fallback attempt)
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
    middleware.append(SessionContextMiddleware())
    return middleware


async def fetch_zeno_anonymous(
    user: Optional[dict] = None,
    system_prompt: Optional[str] = None,
    checkpointer=None,
) -> CompiledStateGraph:
    """Setup the Zeno agent for anonymous users with the provided tools and prompt.

    Pass `checkpointer` (e.g. an in-memory `InMemorySaver`) to keep graph
    state across turns without the Postgres checkpointer; defaults to None
    (stateless).
    """
    zeno_agent = create_agent(
        model=MODEL,
        tools=tools,
        state_schema=AgentState,
        system_prompt=system_prompt or get_prompt(user),
        middleware=_build_middleware(),
        checkpointer=checkpointer,
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
