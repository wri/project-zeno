from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from src.agent.harness.backends.protocol import ZenoBackend
from src.agent.harness.middleware import (
    DatasetTrackingMiddleware,
    SessionContextMiddleware,
)
from src.agent.harness.models import ModelRegistry
from src.agent.harness.prompts import build_orchestrator_prompt
from src.agent.harness.skills import all_skills
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
    backend: ZenoBackend,
    model: BaseChatModel | None = None,
    registry: ModelRegistry | None = None,
) -> CompiledStateGraph:
    if model is None:
        registry = registry or ModelRegistry()
        model = registry.for_langgraph("orchestrator")

    geo = GeoAgent()
    analyst = AnalystAgent(backend=backend)

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
            DatasetTrackingMiddleware(),
        ],
        context_schema=dict,
    )
