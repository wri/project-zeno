"""Agent configurations: which skills and tools (and prompt) load per feature flag.

Profiles form a chain, each one a small delta on its parent:

    base         — the core toolbox (pick_aoi, pick_dataset, pull_data,
                   generate_insights), no skills. Ships on its own so raw
                   tool-calling can be evaluated without recipe guidance.
    default      — base + the core skills (analyze, pull-data, capabilities).
    experimental — default + opt-in skills and standalone tools.

An ``AgentConfig`` declares three things:

- ``extends`` — the parent profile whose skills and tools it inherits.
- ``skills`` — skill names this profile adds. The tools those skills
  ``require:`` are derived from ``ALL_SPECS``, so a profile can never
  advertise a skill whose tools aren't bound — and, conversely, adding a
  tool can never silently activate an unintended skill.
- ``tools`` — specs bound directly, independent of any skill: the base
  profile's core toolbox, or standalone extras no skill's workflow owns.

A skill's ``requires:`` stays a complete list of what its workflow calls,
even when the parent profile already binds those tools — the overlap
dedupes, and the skill stays portable to profiles built on a leaner base.

An optional ``system_prompt`` override replaces the generated prompt
entirely — useful for testing or bespoke agents.

Configs are held in an ``AgentConfigRegistry``, which flattens ``extends``
at registration time. The module-level ``default_registry`` is used in
production; tests create isolated instances and inject them, keeping global
state clean.

To expose a new skill behind a feature flag, register a new ``AgentConfig``
in ``default_registry`` that extends an existing profile (and add any new
tools' specs to ``ALL_SPECS``). Each production profile's full derived
surface is snapshot-tested in ``tests/unit/agent/test_profile_manifest.py``.
"""

from dataclasses import dataclass, field, replace
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

# The core toolbox every profile builds on: resolve an AOI, pick a dataset,
# pull data, generate insights.
BASE_PROFILE = "base"
CORE_TOOLS = (
    pick_aoi_spec,
    pick_dataset_spec,
    pull_data_spec,
    generate_insights_spec,
)

# The core skills layered on the base toolbox.
DEFAULT_PROFILE = "default"
DEFAULT_SKILLS = ("analyze", "pull-data", "capabilities")

# Experimental, opt-in additions over the default profile.
EXPERIMENTAL_PROFILE = "experimental"
EXPERIMENTAL_SKILLS = ("dashboard", "show-imagery", "wri-insights", "explore")
EXPERIMENTAL_TOOLS = (
    inspect_view_context_spec,
    update_insight_display_spec,
    search_insights_spec,
)


@dataclass(frozen=True)
class AgentConfig:
    """A named agent configuration: a parent to extend, declared skills,
    directly-bound tools, and an optional prompt.

    ``extends`` names a parent profile; the registry merges the parent's
    skills and tools into this config at registration time. ``skills`` is
    the capability surface this profile adds; the tools those skills require
    are derived (see ``specs``). ``tools`` holds specs bound directly,
    independent of any skill. ``system_prompt`` overrides the generated
    prompt when set — useful for testing or bespoke agents with a fixed
    persona and no tools.
    """

    name: str
    extends: Optional[str] = None
    skills: tuple[str, ...] = ()
    tools: tuple[ToolSpec, ...] = ()
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
        """The profile's tool specs: the directly-bound ``tools`` plus the
        union of its skills' ``requires`` (and ``read_skill`` when any skill
        is declared), in canonical ``ALL_SPECS`` order."""
        names = {
            tool_name
            for skill_name in self.skills
            for tool_name in get_skill(skill_name).requires  # type: ignore[union-attr]
        }
        if self.skills:
            names.add(read_skill_spec.tool.name)
        names.update(s.tool.name for s in self.tools)
        derived = tuple(s for s in ALL_SPECS if s.tool.name in names)
        unregistered = tuple(
            s for s in self.tools if s.tool.name not in _SPEC_BY_NAME
        )
        return derived + unregistered

    def bound_tools(self) -> list[BaseTool]:
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

    def describe(self) -> str:
        """A plain-text manifest of everything this profile can do, grouped
        by layer: skills (recipes loaded on demand), subagents (tools that
        run their own reasoning), and primitive tools.

        Profiles declare deltas (``extends`` plus their own skills/tools),
        so the full bound surface is not visible at the declaration site —
        this renders it in one place. Snapshot-tested per production profile
        in ``tests/unit/agent/test_profile_manifest.py``.
        """
        lines = [f"profile: {self.name}"]
        if self.extends is not None:
            lines.append(f"extends: {self.extends}")

        def section(title: str, entries: list[str]) -> None:
            lines.append(f"{title}:")
            if entries:
                lines.extend(f"  - {entry}" for entry in entries)
            else:
                lines.append("  (none)")

        skill_entries = []
        for skill in self.skill_metas():
            if skill.requires:
                skill_entries.append(
                    f"{skill.name} (requires: {', '.join(skill.requires)})"
                )
            else:
                skill_entries.append(skill.name)
        section("skills", skill_entries)
        section(
            "subagents",
            [
                s.tool.name
                for s in self.specs
                if s.category is ToolCategory.SUBAGENT
            ],
        )
        section(
            "tools",
            [
                s.tool.name
                for s in self.specs
                if s.category is ToolCategory.PRIMITIVE
            ],
        )
        return "\n".join(lines)


def _merge_skills(
    parent: tuple[str, ...], child: tuple[str, ...]
) -> tuple[str, ...]:
    """Parent's skills first, then the child's new ones; no duplicates."""
    merged = list(parent)
    for name in child:
        if name not in merged:
            merged.append(name)
    return tuple(merged)


def _merge_tools(
    parent: tuple[ToolSpec, ...], child: tuple[ToolSpec, ...]
) -> tuple[ToolSpec, ...]:
    """Parent's tools first, then the child's new ones; deduped by name."""
    merged = list(parent)
    seen = {s.tool.name for s in parent}
    for spec in child:
        if spec.tool.name not in seen:
            merged.append(spec)
            seen.add(spec.tool.name)
    return tuple(merged)


class AgentConfigRegistry:
    """Holds named configs and resolves feature flags to them.

    Create one instance per context (production uses ``default_registry``;
    tests create isolated instances so global state is never mutated).
    """

    def __init__(self) -> None:
        self._configs: dict[str, AgentConfig] = {}

    def register(self, config: AgentConfig) -> None:
        """Store ``config``, flattening its ``extends`` chain first.

        A config that extends another inherits the parent's skills and tools
        and adds its own; the parent must already be registered. The stored
        config is fully flattened (the parent it names was flattened when it
        registered), so lookups never walk the chain.
        """
        if config.extends is not None:
            parent = self._configs.get(config.extends)
            if parent is None:
                raise ValueError(
                    f"profile {config.name!r} extends unknown profile "
                    f"{config.extends!r}; register the parent first"
                )
            config = replace(
                config,
                skills=_merge_skills(parent.skills, config.skills),
                tools=_merge_tools(parent.tools, config.tools),
            )
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


# Production registry — register new flag configs here. Each profile is a
# delta on its parent; parents must be registered before children.
default_registry = AgentConfigRegistry()
default_registry.register(AgentConfig(BASE_PROFILE, tools=CORE_TOOLS))
default_registry.register(
    AgentConfig(
        DEFAULT_PROFILE,
        extends=BASE_PROFILE,
        skills=DEFAULT_SKILLS,
    )
)
default_registry.register(
    AgentConfig(
        EXPERIMENTAL_PROFILE,
        extends=DEFAULT_PROFILE,
        skills=EXPERIMENTAL_SKILLS,
        tools=EXPERIMENTAL_TOOLS,
    )
)
