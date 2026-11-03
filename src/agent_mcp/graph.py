"""The MCP agent: Zeno's graph with the MCP server's tools and no others."""

from datetime import datetime
from typing import Any, Optional

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.messages import ToolMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from src.agent.llms import FALLBACK_MODELS, MODEL
from src.agent.middleware import SessionContextMiddleware, format_session_block
from src.agent.state import AgentState
from src.agent_mcp.projections import PROJECTIONS, aoi_id
from src.agent_mcp.tools import mcp_instructions, mcp_tools
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

PROMPT = """You are Global Nature Watch's Geospatial Agent. You answer user questions by calling tools - never by inventing data.

Today: {today}

A [Session — date] system message is prepended to every model call with the user's current area, dataset and dates, and the ids the tools take for them ("Tool ids" line). The user can also change them on the map, so trust the session block over earlier messages. Reuse its ids; call pick_aoi or pick_dataset again only when the user asks about other places or another dataset.

Call tools one at a time, never in parallel.

# How to use the tools

{instructions}

# Zeno rules

- Call pick_dataset before pulling or charting, so the dataset's layer shows on the map; pass it the options you will pull with.
- For the standard view of a dataset, call generate_insights directly; it pulls the data itself. Call pull_data only when the user wants numbers that the charts do not show.
- When pick_aoi returns candidates, the user sees them as clickable options: ask which one they mean and stop. Their answer comes back as the option text; pass it to pick_aoi.
- When a tool refuses (one area at a time, a dataset without curated charts, a custom area), relay its message and stop.
- After generate_insights, give a short summary of the charts and the dataset's cautions. Never say a chart was made unless generate_insights returned one this turn.
- Reply in the language given in the session block's "Language" line, in markdown, without raw JSON or code blocks.
"""


def _ids_line(state: dict) -> str:
    ids = []
    aois = (state.get("aoi_selection") or {}).get("aois") or []
    if aois:
        ids.append("aoi_ids=" + ", ".join(aoi_id(aoi) for aoi in aois))
    dataset = state.get("dataset") or {}
    if dataset.get("dataset_id") is not None:
        ids.append(f"dataset_id={dataset['dataset_id']}")
        if dataset.get("context_layer"):
            ids.append(f"context_layer={dataset['context_layer']}")
        for param in dataset.get("parameters") or []:
            if param.get("name") == "canopy_cover" and param.get("values"):
                ids.append(f"canopy_cover={max(param['values'])}")
    if state.get("start_date") and state.get("end_date"):
        ids.append(
            f"start_date={state['start_date']}, end_date={state['end_date']}"
        )
    return "Tool ids: " + ("; ".join(ids) if ids else "none")


def mcp_session_block(state: dict) -> str:
    """The session block with the ids the MCP tools take."""
    return format_session_block(state) + "\n" + _ids_line(state)


class ProjectionMiddleware(AgentMiddleware):
    """Write each tool's structured result into the state the frontend
    reads (see ``projections``), on the same update as its ToolMessage.

    The artifact (rows, provenance, the pull script) is dropped from the
    message afterwards, so it is neither checkpointed nor streamed.
    """

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        if not isinstance(result, ToolMessage):
            return result
        artifact = result.artifact
        result.artifact = None
        project = PROJECTIONS.get(result.name)
        if project is None or result.status == "error" or not artifact:
            return result
        update = await project(request.tool_call.get("args") or {}, artifact)
        return Command(update={**update, "messages": [result]})


def _middleware() -> list:
    # Imported here: src.agent.graph imports this module from fetch_zeno.
    from src.agent.graph import handle_tool_errors

    middleware: list = [
        ModelRetryMiddleware(
            max_retries=3,
            backoff_factor=2.0,
            initial_delay=1.0,
            on_failure="error",
        ),
    ]
    if FALLBACK_MODELS:
        middleware.append(ModelFallbackMiddleware(*FALLBACK_MODELS))
    middleware.append(handle_tool_errors)
    middleware.append(ProjectionMiddleware())
    middleware.append(SessionContextMiddleware(format_block=mcp_session_block))
    return middleware


_tools: Optional[list] = None
_instructions: Optional[str] = None


async def get_prompt() -> str:
    global _instructions
    if _instructions is None:
        _instructions = await mcp_instructions()
    return PROMPT.format(
        today=datetime.now().strftime("%Y-%m-%d"), instructions=_instructions
    )


async def fetch_mcp_agent(checkpointer: Any = None) -> CompiledStateGraph:
    """The MCP agent, on the same state schema as Zeno so the API's
    streaming, thread replay and the frontend work unchanged."""
    global _tools
    if _tools is None:
        _tools = await mcp_tools()
    logger.info("Agent profile set", profile="mcp")
    return create_agent(
        model=MODEL,
        tools=_tools,
        state_schema=AgentState,
        system_prompt=await get_prompt(),
        middleware=_middleware(),
        checkpointer=checkpointer,
    )
