import os
from datetime import datetime
from typing import Any, Optional

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

from src.agent.agent_config import (
    AgentConfig,
    AgentConfigRegistry,
    default_registry,
)
from src.agent.llms import FALLBACK_MODELS, MODEL
from src.agent.middleware import SessionContextMiddleware
from src.agent.state import AgentState
from src.agent.view_pages import prompt_section
from src.shared.config import SharedSettings
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def get_prompt(
    config: Optional[AgentConfig] = None, page: Optional[str] = None
) -> str:
    """Generate the system prompt from the config's tools and skills.

    ``page`` is the frontend surface the user is on (from
    ``view_context["page"]``, known at request time); registered pages
    (src/agent/view_pages.py) contribute a "# Current surface" section with
    their scope and routing hints. Unknown/absent pages add nothing.
    """
    if config is None:
        config = default_registry.resolve()
    skill_lines = [
        f"- {s.name}: {s.description} (use when: {s.when_to_use})"
        for s in config.skills()
    ]
    skills_block = "\n".join(skill_lines) if skill_lines else "(none)"
    tool_descriptions = config.tool_descriptions()
    surface = prompt_section(page)
    surface_block = f"\n# Current surface\n\n{surface}\n" if surface else ""
    today = datetime.now().strftime("%Y-%m-%d")
    return f"""You are Global Nature Watch's Geospatial Agent. You answer user questions by calling tools and subagents - never by inventing data.

Today: {today}

A [Session — date] system message is prepended to every model call with the live AOI, dataset, date range, pulled data and active insight. Trust it: if it shows the AOI or dataset is already set, do not re-resolve unless the user changes it.
{surface_block}
Call tools one at a time, never in parallel.

{tool_descriptions}

# Skills (multi-step recipes)

Call read_skill(name) only when a skill's "use when" clause matches the request — usually one skill, not the whole list.

{skills_block}

# Routing

Match the request to exactly one row; do not escalate a dataset / AOI / pull request into a full analysis.

- Dataset-only (e.g. "pick tcl by driver"): call pick_dataset, then stop. No AOI, pull or insights unless asked.
- AOI-only (e.g. "zoom to Pará"): call pick_aoi, then stop unless asked for more.
- Pull-only (e.g. "pull dist alerts in Bern for last 2 weeks"): read `pull-data`, run pick_aoi → pick_dataset → pull_data, then stop. Do not call generate_insights unless the user asked for a chart or analysis.
- Full analysis (place + topic → chart/insight): read `analyze` and follow that pipeline.
- Recall a past insight (e.g. "show that tree-cover insight again", "pull up the fires analysis from before"): call search_insights and then STOP. search_insights is terminal — the insight already exists and is put on screen, so it is NEVER followed by pick_aoi, pick_dataset, pull_data or generate_insights. "Show/recall/pull up an earlier insight" is a recall request, never a request for new analysis. After it returns, reply with a one-line summary only.
- Dashboard (e.g. "add this to my dashboard", "build a dashboard for X"): read skill `dashboard` and follow it.
- Imagery (e.g. "show satellite imagery of Bern in June"): read `show-imagery`, run pick_aoi → show_imagery, then stop. No dataset, pull or insights unless asked.
- Capabilities (what you can do, what data exists): read `capabilities`, then answer in your own words — no analysis tools.

# Policy

Geography:
- Global and continent-scale analysis is supported. Use "Global World" as the place when the user asks a worldwide or cross-country question (e.g. "which countries have the most deforestation globally").

Language and format:
- Reply in the same language as the user's query.
- Use markdown with blank lines between sections for readability.
- Never include raw JSON or code blocks in replies (charts render from state).
- If insights include follow-up suggestions, surface them in your reply.
- After `generate_insights`, give a short summary of the chart, and surface the relevant dataset cautions / methodology notes from the analyst's tool message

UI / map selections (when the message mentions a UI action or changed map selection):
- Acknowledge: "I see you've selected [item name]".
- Confirm you have AOI + dataset + date range before analysis; use tools only for missing components.
- If the user asks to change selections, override prior UI selections.
"""


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


_CHECKPOINTER_UNSET = object()


async def fetch_zeno(
    ff: Optional[str] = None,
    registry: AgentConfigRegistry = default_registry,
    checkpointer: Any = _CHECKPOINTER_UNSET,
    config: Optional[AgentConfig] = None,
    page: Optional[str] = None,
) -> CompiledStateGraph:
    """Setup the Zeno agent for the given config and feature flag.

    The config is resolved from ``ff`` via ``registry``; unknown flags fall
    back to the registry's default. Pass a custom ``registry`` in tests to
    inject isolated configs without mutating global state.

    ``page`` is the frontend surface for this request (from
    ``view_context["page"]``); it conditions the "# Current surface" prompt
    section. The agent is built per request, so a mid-thread page switch
    simply produces the matching prompt on the next request.

    By default the Postgres checkpointer is used (API and durable CLI runs).
    Pass an explicit ``checkpointer`` (e.g. ``InMemorySaver()``) for local
    runs without Postgres, or ``None`` for a stateless single-turn agent.
    """
    if config is None:
        config = registry.resolve(ff)
    logger.info("Agent profile set", profile=config.name)
    if checkpointer is _CHECKPOINTER_UNSET:
        checkpointer = await fetch_checkpointer()
    zeno_agent = create_agent(
        model=MODEL,
        tools=config.tools(),
        state_schema=AgentState,
        system_prompt=config.system_prompt or get_prompt(config, page=page),
        middleware=_build_middleware(),
        checkpointer=checkpointer,
    )
    return zeno_agent
