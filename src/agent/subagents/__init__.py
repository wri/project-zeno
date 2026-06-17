"""Subagents — tools that own their reasoning and a dedicated system prompt.

Each subagent is exposed to the orchestrator as a single, trivially-callable
tool, but internally runs its own LLM reasoning to do its job. This keeps the
orchestrator's tool calls simple and the domain logic behind a clean boundary.
"""

from src.agent.subagents.analyst import Analyst, generate_insights
from src.agent.subagents.pick_aoi import Geocoder, pick_aoi
from src.agent.subagents.pick_dataset import DatasetSelector, pick_dataset
from src.agent.subagents.search import search_blogs

__all__ = [
    "Analyst",
    "DatasetSelector",
    "Geocoder",
    "generate_insights",
    "pick_aoi",
    "pick_dataset",
    "search_blogs",
]
