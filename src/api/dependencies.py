"""FastAPI-edge dependency declarations."""

from functools import lru_cache

from src.agent.agent_config import (
    CORE_SPECS,
    DEFAULT_PROFILE,
    AgentConfig,
    AgentConfigRegistry,
)


@lru_cache
def get_registry() -> AgentConfigRegistry:
    registry = AgentConfigRegistry()
    registry.register(AgentConfig(DEFAULT_PROFILE, specs=CORE_SPECS))
    return registry
