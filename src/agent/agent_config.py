"""Agent configurations: which skills (and prompt) load per feature flag.

An ``AgentConfig`` declares its capability surface as a tuple of *skill
names*; the tools those skills ``require:`` are derived from ``ALL_SPECS``,
so a profile can never advertise a skill whose tools aren't bound — and,
conversely, adding a tool can never silently activate an unintended skill.
Tools useful on their own (not part of any skill's workflow) go in
``extra_tools``. An optional ``system_prompt`` override replaces the
generated prompt entirely — useful for testing or bespoke agents.

Configs are held in an ``AgentConfigRegistry``. The module-level
``default_registry`` is used in production; tests create isolated instances
and inject them, keeping global state clean.

To expose a new skill behind a feature flag, register a new ``AgentConfig``
in ``default_registry`` with the flag name (and add any new tools' specs to
``ALL_SPECS``).
"""

from dataclasses import dataclass, field
from typing import Optional

from langchain_core.tools import BaseTool

from src.agent.skills import SkillMeta, all_skills, get_skill
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

# Every registered tool spec, in canonical system-prompt order. Profiles
# derive their spec tuples from this, so a tool's position here is its
# position in every profile's prompt.
ALL_SPECS = (
    pick_aoi_spec,
    pick_dataset_spec,
    pull_data_spec,
    generate_insights_spec,
    read_skill_spec,
    inspect_view_context_spec,
    show_imagery_spec,
    search_blogs_spec,
    update_insight_display_spec,
    search_insights_spec,
    create_dashboard_spec,
    add_to_dashboard_spec,
    add_map_widget_spec,
)
_SPEC_BY_NAME = {s.tool.name: s for s in ALL_SPECS}

DEFAULT_PROFILE = "default"
DEFAULT_SKILLS = ("analyze", "pull-data", "capabilities")

# Experimental, opt-in skills/tools layered on top of the default set.
EXPERIMENTAL_PROFILE = "experimental"
EXPERIMENTAL_SKILLS = (
    *DEFAULT_SKILLS,
    "dashboard",
    "show-imagery",
    "wri-insights",
    "explore",
)


@dataclass(frozen=True)
class AgentConfig:
    """A named agent configuration: declared skills and an optional prompt.

    ``skills`` is the capability surface; the tools those skills require are
    derived (see ``specs``). ``extra_tools`` holds specs not tied to any
    skill's workflow. ``system_prompt`` overrides the generated prompt when
    set — useful for testing or bespoke agents with a fixed persona and no
    tools.
    """

    name: str
    skills: tuple[str, ...] = ()
    extra_tools: tuple[ToolSpec, ...] = ()
    system_prompt: Optional[str] = field(default=None)

    def __post_init__(self) -> None:
        for skill_name in self.skills:
            skill = get_skill(skill_name)
            if skill is None:
                raise ValueError(
                    f"profile {self.name!r} declares unknown skill "
                    f"{skill_name!r}"
                )
            unknown = [t for t in skill.requires if t not in _SPEC_BY_NAME]
            if unknown:
                raise ValueError(
                    f"skill {skill_name!r} (declared by profile "
                    f"{self.name!r}) requires tools missing from ALL_SPECS: "
                    f"{unknown}"
                )

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        """The profile's tool specs: the union of its skills' ``requires``
        (plus ``read_skill`` when any skill is declared) and ``extra_tools``,
        in canonical ``ALL_SPECS`` order."""
        names = {
            tool_name
            for skill_name in self.skills
            for tool_name in get_skill(skill_name).requires  # type: ignore[union-attr]
        }
        if self.skills:
            names.add(read_skill_spec.tool.name)
        names.update(s.tool.name for s in self.extra_tools)
        derived = tuple(s for s in ALL_SPECS if s.tool.name in names)
        unregistered = tuple(
            s for s in self.extra_tools if s.tool.name not in _SPEC_BY_NAME
        )
        return derived + unregistered

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

    def skill_metas(self) -> list[SkillMeta]:
        declared = set(self.skills)
        return [sk for sk in all_skills() if sk.name in declared]

    def availability(self) -> Availability:
        """What this profile can route to — the declared skills and the tools
        derived from them, so prompt builders and ``read_skill`` never serve
        a skill or tool the profile doesn't declare."""
        return Availability(
            skills=frozenset(self.skills),
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

    def configs(self) -> tuple[AgentConfig, ...]:
        """All registered configs, e.g. for invariant checks across profiles."""
        return tuple(self._configs.values())

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
default_registry.register(AgentConfig(DEFAULT_PROFILE, skills=DEFAULT_SKILLS))
default_registry.register(
    AgentConfig(
        EXPERIMENTAL_PROFILE,
        skills=EXPERIMENTAL_SKILLS,
        extra_tools=(
            inspect_view_context_spec,
            update_insight_display_spec,
            search_insights_spec,
        ),
    )
)
