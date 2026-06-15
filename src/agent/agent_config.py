"""Agent configurations: which tools (and prompt) load per feature flag.

An ``AgentConfig`` bundles a set of ``ToolSpec`` objects together so the
system prompt can never describe a tool that isn't bound. An optional
``system_prompt`` override replaces the generated prompt entirely — useful
for testing or bespoke agents.

Configs are held in an ``AgentConfigRegistry``. The module-level
``default_registry`` is used in production; tests create isolated instances
and inject them, keeping global state clean.

To expose a new tool behind a feature flag, register a new ``AgentConfig``
in ``default_registry`` with the flag name.
"""

from dataclasses import dataclass, field
from typing import Optional

from langchain_core.tools import BaseTool

from src.agent.skills import SkillMeta, all_skills
from src.agent.skills.tool import SPEC as read_skill_spec
from src.agent.subagents.analyst.tool import SPEC as generate_insights_spec
from src.agent.subagents.pick_aoi.tool import SPEC as pick_aoi_spec
from src.agent.subagents.pick_dataset.tool import SPEC as pick_dataset_spec
from src.agent.tool_spec import CATEGORY_HEADERS, ToolCategory, ToolSpec
from src.agent.tools.pull_data import SPEC as pull_data_spec
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_PROFILE = "default"

CORE_SPECS = (
    pick_aoi_spec,
    pick_dataset_spec,
    pull_data_spec,
    generate_insights_spec,
    read_skill_spec,
)


@dataclass(frozen=True)
class AgentConfig:
    """A named agent configuration: a set of tools and an optional prompt.

    ``system_prompt`` overrides the generated prompt when set — useful for
    testing or bespoke agents with a fixed persona and no tools.
    """

    name: str
    specs: tuple[ToolSpec, ...]
    system_prompt: Optional[str] = field(default=None)

    def tools(self) -> list[BaseTool]:
        return [s.tool for s in self.specs]

    def tool_descriptions(self) -> str:
        blocks = []
        for category in ToolCategory:
            fragments = [
                s.prompt_fragment for s in self.specs if s.category == category
            ]
            if fragments:
                blocks.append(
                    CATEGORY_HEADERS[category] + "\n\n" + "\n".join(fragments)
                )
        return "\n\n".join(blocks)

    def skills(self) -> list[SkillMeta]:
        available = {s.tool.name for s in self.specs}
        return [sk for sk in all_skills() if set(sk.requires) <= available]


class AgentConfigRegistry:
    """Holds named configs and resolves feature flags to them.

    Create one instance per context (production uses ``default_registry``;
    tests create isolated instances so global state is never mutated).
    """

    def __init__(self) -> None:
        self._configs: dict[str, AgentConfig] = {}

    def register(self, config: AgentConfig) -> None:
        self._configs[config.name] = config

    def resolve(self, ff: Optional[str] = None) -> AgentConfig:
        """Return the config for ``ff``, falling back to the default."""
        if ff and ff in self._configs:
            return self._configs[ff]
        if ff:
            logger.warning(
                "Unknown feature flag %r, falling back to %r",
                ff,
                DEFAULT_PROFILE,
            )
        return self._configs[DEFAULT_PROFILE]


# Production registry — register new flag configs here.
default_registry = AgentConfigRegistry()
default_registry.register(AgentConfig(DEFAULT_PROFILE, specs=CORE_SPECS))
