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
from src.agent.subagents.search.blog import SPEC as search_blogs_spec
from src.agent.tool_spec import Availability, ToolCategory, ToolSpec
from src.agent.tools.add_map_widget import SPEC as add_map_widget_spec
from src.agent.tools.add_to_dashboard import SPEC as add_to_dashboard_spec
from src.agent.tools.create_dashboard import SPEC as create_dashboard_spec
from src.agent.tools.inspect_view_context import (
    SPEC as inspect_view_context_spec,
)
from src.agent.tools.pull_data import SPEC as pull_data_spec
from src.agent.tools.search_insights import SPEC as search_insights_spec
from src.agent.tools.show_imagery import SPEC as show_imagery_spec
from src.agent.tools.update_insight_display import (
    SPEC as update_insight_display_spec,
)
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

# Experimental, opt-in tools layered on top of the core set.
EXPERIMENTAL_PROFILE = "experimental"
EXPERIMENTAL_SPECS = (
    *CORE_SPECS,
    inspect_view_context_spec,
    show_imagery_spec,
    search_blogs_spec,
    update_insight_display_spec,
    search_insights_spec,
    create_dashboard_spec,
    add_to_dashboard_spec,
    add_map_widget_spec,
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
                blocks.append(category + "\n\n" + "\n".join(fragments))
        return "\n\n".join(blocks)

    def tool_names(self) -> frozenset[str]:
        return frozenset(s.tool.name for s in self.specs)

    def skills(self) -> list[SkillMeta]:
        available = self.tool_names()
        return [sk for sk in all_skills() if set(sk.requires) <= available]

    def availability(self) -> Availability:
        """What this profile can route to — the same rule read_skill enforces
        at call time (a skill's ``requires`` must all be bound), so prompt
        builders never advertise a skill or tool the model would just get
        "not found"/refused for."""
        return Availability(
            skills=frozenset(sk.name for sk in self.skills()),
            tools=self.tool_names(),
        )


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
default_registry.register(
    AgentConfig(EXPERIMENTAL_PROFILE, specs=EXPERIMENTAL_SPECS)
)
