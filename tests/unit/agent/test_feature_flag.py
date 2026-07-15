"""Tests for AgentConfig, AgentConfigRegistry, and feature flags."""

import pytest
from langchain_core.tools import tool

from src.agent.agent_config import (
    BASE_PROFILE,
    DEFAULT_PROFILE,
    DEFAULT_SKILLS,
    EXPERIMENTAL_PROFILE,
    AgentConfig,
    AgentConfigRegistry,
    default_registry,
)
from src.agent.skills import SkillMeta
from src.agent.tool_spec import ToolCategory, ToolSpec, bound_availability

# --- Lightweight test fixtures -----------------------------------------------


@tool
def _fake_tool(x: str) -> str:
    """A lightweight fake tool used only in unit tests."""
    return x


FAKE_SPEC = ToolSpec(
    _fake_tool, ToolCategory.PRIMITIVE, "- _fake_tool: test only"
)


# --- AgentConfigRegistry -----------------------------------------------------


def test_registry_resolves_known_ff():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default"))
    registry.register(AgentConfig("blog", tools=(FAKE_SPEC,)))
    assert registry.resolve("blog").name == "blog"


def test_registry_falls_back_to_default_for_unknown_ff():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default"))
    assert registry.resolve("bogus").name == DEFAULT_PROFILE


def test_registry_falls_back_to_default_for_none():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default"))
    assert registry.resolve(None).name == DEFAULT_PROFILE


def test_registry_instances_are_isolated():
    registry_a = AgentConfigRegistry()
    registry_a.register(AgentConfig("default"))
    registry_a.register(AgentConfig("cat", system_prompt="Say cat."))

    registry_b = AgentConfigRegistry()
    registry_b.register(AgentConfig("default"))

    assert registry_a.resolve("cat").name == "cat"
    assert registry_b.resolve("cat").name == DEFAULT_PROFILE


# --- AgentConfigRegistry: extends --------------------------------------------


def test_extends_merges_parent_skills_and_tools():
    """A child profile is its parent plus its own additions — parent's
    entries first, duplicates removed."""
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default", tools=(FAKE_SPEC,)))
    registry.register(
        AgentConfig("child", extends="default", skills=("capabilities",))
    )
    child = registry.resolve("child")
    assert child.skills == ("capabilities",)
    assert child.tools == (FAKE_SPEC,)


def test_extends_chain_flattens_through_grandparent():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default", tools=(FAKE_SPEC,)))
    registry.register(
        AgentConfig("child", extends="default", skills=("capabilities",))
    )
    registry.register(
        AgentConfig("grandchild", extends="child", skills=("analyze",))
    )
    grandchild = registry.resolve("grandchild")
    assert grandchild.skills == ("capabilities", "analyze")
    assert grandchild.tools == (FAKE_SPEC,)


def test_extends_deduplicates_reinherited_entries():
    registry = AgentConfigRegistry()
    registry.register(
        AgentConfig("default", skills=("capabilities",), tools=(FAKE_SPEC,))
    )
    registry.register(
        AgentConfig(
            "child",
            extends="default",
            skills=("capabilities", "analyze"),
            tools=(FAKE_SPEC,),
        )
    )
    child = registry.resolve("child")
    assert child.skills == ("capabilities", "analyze")
    assert child.tools == (FAKE_SPEC,)


def test_extends_unknown_parent_raises():
    """A child registered before (or without) its parent is a wiring bug —
    fail loudly instead of silently dropping the inherited surface."""
    registry = AgentConfigRegistry()
    with pytest.raises(ValueError, match="extends unknown profile"):
        registry.register(AgentConfig("child", extends="nope"))


# --- AgentConfig: skills-first construction ----------------------------------


def test_config_rejects_unknown_skill_name():
    """A typo'd skill declaration must fail at registration time, not
    surface as a runtime "skill not found" the model can't act on."""
    with pytest.raises(ValueError, match="unknown skill 'does-not-exist'"):
        AgentConfig("test", skills=("does-not-exist",))


def test_config_rejects_skill_requiring_unregistered_tool(monkeypatch):
    """A skill whose ``requires:`` names a tool missing from ALL_SPECS could
    never bind its workflow — refuse the profile outright."""
    fake = SkillMeta(
        name="broken",
        description="",
        when_to_use="",
        body="",
        requires=("no_such_tool",),
    )
    monkeypatch.setattr(
        "src.agent.agent_config.get_skill",
        lambda name: fake if name == "broken" else None,
    )
    with pytest.raises(ValueError, match="no_such_tool"):
        AgentConfig("test", skills=("broken",))


def test_config_derives_tools_from_declared_skills():
    c = AgentConfig("test", skills=("analyze",))
    assert c.tool_names() == frozenset(
        {
            "pick_aoi",
            "pick_dataset",
            "pull_data",
            "generate_insights",
            "read_skill",
        }
    )


def test_config_without_skills_has_no_read_skill():
    """read_skill only rides along when there are skills to read."""
    c = AgentConfig("test", tools=(FAKE_SPEC,))
    assert c.tool_names() == frozenset({"_fake_tool"})


def test_directly_bound_tools_do_not_activate_skills():
    """The bug this design kills: under tools-first profiles, adding a tool
    could silently activate any skill whose ``requires`` it completed. Now
    the capability surface is exactly what's declared."""
    from src.agent.subagents.pick_aoi.tool import SPEC as pick_aoi_spec
    from src.agent.tools.show_imagery import SPEC as show_imagery_spec

    c = AgentConfig(
        "test",
        skills=("capabilities",),
        tools=(pick_aoi_spec, show_imagery_spec),
    )
    # pick_aoi + show_imagery satisfy show-imagery's requires, but it was
    # never declared — it must not be advertised or counted available.
    assert {s.name for s in c.skill_metas()} == {"capabilities"}
    assert not c.availability().has_skill("show-imagery")


def test_config_bound_tools_returns_bound_tools():
    c = AgentConfig("test", tools=(FAKE_SPEC,))
    assert _fake_tool in c.bound_tools()


def test_config_tool_descriptions_includes_bound_tool():
    c = AgentConfig("test", tools=(FAKE_SPEC,))
    assert "_fake_tool" in c.tool_descriptions()


def test_config_tool_descriptions_excludes_unbound_tool():
    c = AgentConfig("test")
    assert "_fake_tool" not in c.tool_descriptions()


# --- Structural invariants ---------------------------------------------------


def test_prompt_describes_exactly_bound_tools():
    """Prompt only mentions tools that are actually bound."""
    config = default_registry.resolve(None)
    descriptions = config.tool_descriptions()
    for spec in config.specs:
        assert spec.tool.name in descriptions
    assert "_fake_tool" not in descriptions


def test_declared_skills_always_have_their_tools_bound():
    """Correct-by-construction: a declared skill's requires are derived
    into the profile's tool set, never filtered against it."""
    for config in default_registry.configs():
        available = config.tool_names()
        for skill in config.skill_metas():
            assert set(skill.requires) <= available


def test_default_config_advertises_core_skills():
    config = default_registry.resolve(None)
    assert {s.name for s in config.skill_metas()} == set(DEFAULT_SKILLS)


def test_base_profile_binds_the_core_toolbox_and_no_skills():
    """The base profile is the floor every other profile builds on: the four
    core tools, no skills — and therefore no read_skill."""
    config = default_registry.resolve(BASE_PROFILE)
    assert config.skills == ()
    assert config.tool_names() == frozenset(
        {
            "pick_aoi",
            "pick_dataset",
            "pull_data",
            "generate_insights",
        }
    )


def test_default_profile_derives_exactly_the_core_tools():
    """Pin the derived tool set so a skill frontmatter change that would
    alter production bindings is a visible test failure."""
    config = default_registry.resolve(DEFAULT_PROFILE)
    assert config.tool_names() == frozenset(
        {
            "pick_aoi",
            "pick_dataset",
            "pull_data",
            "generate_insights",
            "read_skill",
        }
    )


def test_experimental_profile_derives_exactly_the_experimental_tools():
    config = default_registry.resolve(EXPERIMENTAL_PROFILE)
    assert config.tool_names() == frozenset(
        {
            "pick_aoi",
            "pick_dataset",
            "pull_data",
            "generate_insights",
            "read_skill",
            "inspect_view_context",
            "show_imagery",
            "search_blogs",
            "update_insight_display",
            "search_insights",
            "create_dashboard",
            "add_to_dashboard",
            "add_map_widget",
            "add_text_widget",
            "edit_text_widget",
        }
    )


async def test_fetch_zeno_binds_the_resolved_configs_availability():
    """read_skill relies on bound_availability() reflecting the profile that
    was actually resolved for this request, not just what's listed in the
    prompt."""
    from langgraph.checkpoint.memory import InMemorySaver

    from src.agent.graph import fetch_zeno

    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default"))
    registry.register(
        AgentConfig("fake", skills=("capabilities",), tools=(FAKE_SPEC,))
    )

    await fetch_zeno(
        ff="fake", registry=registry, checkpointer=InMemorySaver()
    )
    available = bound_availability()
    assert available.skills == frozenset({"capabilities"})
    assert available.tools == frozenset({"_fake_tool", "read_skill"})


def test_experimental_config_adds_experimental_tools_and_skills():
    """The experimental profile layers show_imagery and search_blogs (and
    their skills) on top of the default set; the default profile exposes
    none."""
    default = default_registry.resolve(DEFAULT_PROFILE)
    experimental = default_registry.resolve(EXPERIMENTAL_PROFILE)

    default_tools = {t.name for t in default.bound_tools()}
    experimental_tools = {t.name for t in experimental.bound_tools()}
    assert {"show_imagery", "search_blogs"} & default_tools == set()
    assert {"show_imagery", "search_blogs"} <= experimental_tools

    default_skills = {s.name for s in default.skill_metas()}
    experimental_skills = {s.name for s in experimental.skill_metas()}
    assert {
        "show-imagery",
        "explore",
        "wri-insights",
    } & default_skills == set()
    assert {"show-imagery", "explore", "wri-insights"} <= experimental_skills
