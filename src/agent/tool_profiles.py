"""Agent tool profiles: which tools (and their prompt descriptions) load per conversation.

A *profile* bundles a set of tools together with the prompt fragment that
describes each one, so the system prompt can never describe a tool that isn't
bound (or omit one that is) — the two are derived from the same source.

The profile is chosen per conversation from the user's ``agent_profile`` field:
- users set to ``experimental`` get that profile, which adds experimental tools
  on top of the production set;
- everyone else (incl. anonymous) gets the production ``default``.

To expose a new experimental tool, register it in ``TOOL_REGISTRY`` and add its
name to ``_EXPERIMENTAL_TOOLS``. Promote it to ``_CORE_TOOLS`` once it ships to
production.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from langchain_core.tools import BaseTool

from src.agent.skills import SkillMeta, all_skills, read_skill
from src.agent.subagents import generate_insights, pick_aoi, pick_dataset
from src.agent.tools import pull_data
from src.api.data_models import AgentProfile
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


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

DEFAULT_PROFILE = AgentProfile.DEFAULT.value
EXPERIMENTAL_PROFILE = AgentProfile.EXPERIMENTAL.value

# Tools every user gets in production.
_CORE_TOOLS = [
    "pick_aoi",
    "pick_dataset",
    "pull_data",
    "generate_insights",
    "read_skill",
]

# Experimental tools, exposed only to users with agent_profile=experimental.
# Add new tools here first (e.g. "show_imagery"); promote to _CORE_TOOLS to ship.
_EXPERIMENTAL_TOOLS: list[str] = []


@dataclass(frozen=True)
class Profile:
    """A named tool set the agent loads for a conversation.

    Holds only the tool *names*; the tool objects, their prompt fragments and
    the skill registry stay single-sourced in ``TOOL_REGISTRY`` / ``all_skills``.
    Add fields here (e.g. a model override or extra prompt block) to parametrize
    profiles further.
    """

    name: str
    tool_names: tuple[str, ...]

    def tools(self) -> list[BaseTool]:
        """The tool objects bound to the agent for this profile."""
        return [TOOL_REGISTRY[name].tool for name in self.tool_names]

    def tool_descriptions(self) -> str:
        """Render the Tools + Subagents prompt sections for this profile.

        Grouped by category so the prompt only ever describes tools that are
        actually bound for this profile.
        """
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
        """Skills whose required tools are all bound in this profile.

        A skill recipe directs the model to call specific tools (declared in its
        ``requires`` frontmatter), so we only advertise a skill when this
        profile binds every tool it needs — otherwise the workflow would tell
        the model to call a tool that isn't available.
        """
        available = set(self.tool_names)
        return [s for s in all_skills() if set(s.requires) <= available]


PROFILES: dict[str, Profile] = {
    DEFAULT_PROFILE: Profile(DEFAULT_PROFILE, tuple(_CORE_TOOLS)),
    EXPERIMENTAL_PROFILE: Profile(
        EXPERIMENTAL_PROFILE, tuple(_CORE_TOOLS + _EXPERIMENTAL_TOOLS)
    ),
}


def get_profile(name: str) -> Profile:
    """Look up a profile by name, falling back to the default if unknown."""
    profile = PROFILES.get(name)
    if profile is None:
        logger.warning(
            "Unknown tool profile %r, falling back to %r",
            name,
            DEFAULT_PROFILE,
        )
        return PROFILES[DEFAULT_PROFILE]
    return profile


def resolve_profile(user: Optional[dict] = None) -> Profile:
    """Pick the tool profile for a conversation from the user's agent_profile.

    Reads the user's ``agent_profile`` field; unknown or missing values (incl.
    anonymous users) fall back to the production default via ``get_profile``.
    """
    name = (user or {}).get("agent_profile") or DEFAULT_PROFILE
    return get_profile(str(name))
