"""Agent tool profiles: which tools (and prompt) load per feature flag.

A *profile* bundles a named set of tools together with the prompt fragments
that describe each one, so the system prompt can never describe a tool that
isn't bound (or omit one that is). An optional ``system_prompt`` override
replaces the generated prompt entirely — useful for testing or bespoke agents.

Profiles are held in a ``ProfileRegistry``. The module-level
``default_registry`` is used in production; tests create isolated instances
and inject them, keeping global state clean.

To expose a new tool behind a feature flag:
1. Register it in ``TOOL_REGISTRY``.
2. Register a new ``Profile`` in ``default_registry`` with the flag name.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from langchain_core.tools import BaseTool

from src.agent.skills import SkillMeta, all_skills, read_skill
from src.agent.subagents import generate_insights, pick_aoi, pick_dataset
from src.agent.tools import pull_data
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_PROFILE = "default"


class ToolCategory(str, Enum):
    """How a tool is grouped under a heading in the system prompt."""

    PRIMITIVE = "primitive"
    SUBAGENT = "subagent"


_CATEGORY_HEADERS = {
    ToolCategory.PRIMITIVE: "# Tools (primitives — call when you need them)",
    ToolCategory.SUBAGENT: "# Subagents (call as tools — each does its own reasoning; just forward the user's intent)",
}


@dataclass(frozen=True)
class ToolSpec:
    """A tool plus the prompt fragment that teaches the model to use it."""

    tool: BaseTool
    category: ToolCategory
    prompt_fragment: str


# Every tool the agent can load, keyed by name. Profiles reference these names.
TOOL_REGISTRY: dict[str, ToolSpec] = {
    "pull_data": ToolSpec(
        pull_data,
        ToolCategory.PRIMITIVE,
        "- pull_data(query): fetch data for the AOI and dataset currently in state. Run pick_aoi and pick_dataset first.",
    ),
    "read_skill": ToolSpec(
        read_skill,
        ToolCategory.PRIMITIVE,
        "- read_skill(name): load a skill's full workflow — call it once, after you have committed to using that skill.",
    ),
    "pick_aoi": ToolSpec(
        pick_aoi,
        ToolCategory.SUBAGENT,
        '- pick_aoi(question): natural-language geocoder. Pass the place request verbatim ("tree cover loss in Pará, Brazil", "the districts of Odisha", "forest loss worldwide"); it extracts, translates and resolves the place — and any subregions — itself. Updates the AOI in state, or returns a clarifying question.',
    ),
    "pick_dataset": ToolSpec(
        pick_dataset,
        ToolCategory.SUBAGENT,
        "- pick_dataset(query): dataset-selection subagent. Picks the dataset, context layer and date range that best answer the request. May return no dataset if none is a good fit — in that case relay its explanation and closest alternatives to the user; do not proceed to pull_data. Call it again whenever the user changes the dataset, context layer or parameters.",
    ),
    "generate_insights": ToolSpec(
        generate_insights,
        ToolCategory.SUBAGENT,
        "- generate_insights(query): analyst subagent. Turns pulled data into one chart insight with follow-up suggestions. Requires pull_data to have run first.",
    ),
}

_CORE_TOOLS = [
    "pick_aoi",
    "pick_dataset",
    "pull_data",
    "generate_insights",
    "read_skill",
]


@dataclass(frozen=True)
class Profile:
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


class ProfileRegistry:
    """Holds named profiles and resolves feature flags to them.

    Create one instance per context (production uses ``default_registry``;
    tests create isolated instances so global state is never mutated).
    """

    def __init__(self) -> None:
        self._profiles: dict[str, Profile] = {}

    def register(self, profile: Profile) -> None:
        self._profiles[profile.name] = profile

    def resolve(self, ff: Optional[str] = None) -> Profile:
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
default_registry = ProfileRegistry()
default_registry.register(Profile(DEFAULT_PROFILE, tuple(_CORE_TOOLS)))
