"""Agent configurations: which tools (and prompt) load per feature flag.

An ``AgentConfig`` bundles a named set of tools together with the prompt
fragments that describe each one, so the system prompt can never describe a
tool that isn't bound. An optional ``system_prompt`` override replaces the
generated prompt entirely — useful for testing or bespoke agents.

Configs are held in an ``AgentConfigRegistry``. The module-level
``default_registry`` is used in production; tests create isolated instances
and inject them, keeping global state clean.

To expose a new tool behind a feature flag:
1. Register it in ``TOOL_REGISTRY``.
2. Register a new ``AgentConfig`` in ``default_registry`` with the flag name.
"""

from dataclasses import dataclass, field
from typing import Optional

from langchain_core.tools import BaseTool

# Prompt fragments live next to each tool's implementation, not here.
from src.agent.skills import SkillMeta, all_skills
from src.agent.skills.tool import SPEC as _READ_SKILL_SPEC
from src.agent.subagents.analyst.tool import SPEC as _GENERATE_INSIGHTS_SPEC
from src.agent.subagents.pick_aoi.tool import SPEC as _PICK_AOI_SPEC
from src.agent.subagents.pick_dataset.tool import SPEC as _PICK_DATASET_SPEC
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.pull_data import SPEC as _PULL_DATA_SPEC
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_PROFILE = "default"

_CATEGORY_HEADERS = {
    ToolCategory.PRIMITIVE: "# Tools (primitives — call when you need them)",
    ToolCategory.SUBAGENT: "# Subagents (call as tools — each does its own reasoning; just forward the user's intent)",
}

TOOL_REGISTRY: dict[str, ToolSpec] = {
    s.tool.name: s
    for s in [
        _PULL_DATA_SPEC,
        _READ_SKILL_SPEC,
        _PICK_AOI_SPEC,
        _PICK_DATASET_SPEC,
        _GENERATE_INSIGHTS_SPEC,
    ]
}

_CORE_TOOLS = [
    "pick_aoi",
    "pick_dataset",
    "pull_data",
    "generate_insights",
    "read_skill",
]


@dataclass(frozen=True)
class AgentConfig:
    """A named tool set the agent loads for a conversation.

    ``system_prompt`` overrides the generated prompt when set — useful for
    testing or bespoke agents with a fixed persona and no tools.
    """

    name: str
    tool_names: tuple[str, ...]
    system_prompt: Optional[str] = field(default=None)

    def tools(self) -> list[BaseTool]:
        return [TOOL_REGISTRY[name].tool for name in self.tool_names]

    def tool_descriptions(self) -> str:
        blocks = []
        for category in ToolCategory:
            fragments = [
                TOOL_REGISTRY[name].prompt_fragment
                for name in self.tool_names
                if TOOL_REGISTRY[name].category == category
            ]
            if fragments:
                blocks.append(
                    _CATEGORY_HEADERS[category] + "\n\n" + "\n".join(fragments)
                )
        return "\n\n".join(blocks)

    def skills(self) -> list[SkillMeta]:
        available = set(self.tool_names)
        return [s for s in all_skills() if set(s.requires) <= available]


class AgentConfigRegistry:
    """Holds named profiles and resolves feature flags to them.

    Create one instance per context (production uses ``default_registry``;
    tests create isolated instances so global state is never mutated).
    """

    def __init__(self) -> None:
        self._profiles: dict[str, AgentConfig] = {}

    def register(self, profile: AgentConfig) -> None:
        self._profiles[profile.name] = profile

    def resolve(self, ff: Optional[str] = None) -> AgentConfig:
        """Return the profile for ``ff``, falling back to the default."""
        if ff and ff in self._profiles:
            return self._profiles[ff]
        if ff:
            logger.warning(
                "Unknown feature flag %r, falling back to %r",
                ff,
                DEFAULT_PROFILE,
            )
        return self._profiles[DEFAULT_PROFILE]


# Production registry — add new flag profiles here.
default_registry = AgentConfigRegistry()
default_registry.register(AgentConfig(DEFAULT_PROFILE, tuple(_CORE_TOOLS)))
