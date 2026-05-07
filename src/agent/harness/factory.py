"""Factory for assembling the Zeno orchestrator agent."""

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from src.agent.harness.middleware import SessionContextMiddleware
from src.agent.harness.models import ModelRegistry
from src.agent.harness.prompts import build_orchestrator_prompt
from src.agent.harness.skills import all_skills
from src.agent.harness.state import ZenoState
from src.agent.harness.subagents.analyst import AnalystAgent
from src.agent.harness.subagents.geo import GeoAgent
from src.agent.harness.subagents.wrap import (
    make_analyst_tool,
    make_geo_tool,
)
from src.agent.harness.tools import (
    execute,
    fetch,
    get_artifact,
    list_datasets,
    read_skill,
    update_artifact,
    zoom_map,
)


def create_zeno_agent(
    model: BaseChatModel | None = None,
    registry: ModelRegistry | None = None,
    store: BaseStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Create the Zeno orchestrator agent.

    Args:
        model: LLM to use. Falls back to ModelRegistry default.
        registry: Model registry for component-based model selection.
        store: LangGraph Store for data/artifact persistence.
            Defaults to InMemoryStore.
        checkpointer: LangGraph checkpointer for state persistence across
            turns. Defaults to MemorySaver (in-memory).
    """
    if model is None:
        registry = registry or ModelRegistry()
        model = registry.for_langgraph("orchestrator")

    if store is None:
        store = InMemoryStore()

    if checkpointer is None:
        checkpointer = MemorySaver()

    geo = GeoAgent()
    analyst = AnalystAgent(store=store)

    tools = [
        list_datasets,
        fetch,
        execute,
        get_artifact,
        update_artifact,
        zoom_map,
        read_skill,
        make_geo_tool(geo),
        make_analyst_tool(analyst),
    ]

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=build_orchestrator_prompt(all_skills()),
        middleware=[
            SessionContextMiddleware(),
        ],
        state_schema=ZenoState,
        store=store,
        checkpointer=checkpointer,
    )
