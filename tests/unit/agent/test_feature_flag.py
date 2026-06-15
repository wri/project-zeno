"""Tests for agent tool profiles and AgentConfigRegistry."""

from src.agent.agent_config import (
    DEFAULT_PROFILE,
    TOOL_REGISTRY,
    AgentConfig,
    AgentConfigRegistry,
    default_registry,
)
from src.agent.skills import all_skills

# --- AgentConfigRegistry ---------------------------------------------------------


def test_registry_resolves_known_ff():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default", ()))
    registry.register(AgentConfig("blog", ("pick_aoi",)))
    assert registry.resolve("blog").name == "blog"


def test_registry_falls_back_to_default_for_unknown_ff():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default", ()))
    assert registry.resolve("bogus").name == DEFAULT_PROFILE


def test_registry_falls_back_to_default_for_none():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default", ()))
    assert registry.resolve(None).name == DEFAULT_PROFILE


def test_registry_instances_are_isolated():
    registry_a = AgentConfigRegistry()
    registry_a.register(AgentConfig("default", ()))
    registry_a.register(AgentConfig("cat", (), "Say only the word 'cat'."))

    registry_b = AgentConfigRegistry()
    registry_b.register(AgentConfig("default", ()))

    assert registry_a.resolve("cat").name == "cat"
    assert registry_b.resolve("cat").name == DEFAULT_PROFILE  # not leaked


def test_profile_system_prompt_override():
    p = AgentConfig("cat", (), "Say only the word 'cat'.")
    assert p.system_prompt == "Say only the word 'cat'."


def test_profile_system_prompt_defaults_to_none():
    p = AgentConfig("default", ("pick_aoi",))
    assert p.system_prompt is None


# --- default_registry --------------------------------------------------------


def test_default_registry_contains_default_profile():
    assert default_registry.resolve(None).name == DEFAULT_PROFILE


def test_default_registry_unknown_ff_falls_back():
    assert default_registry.resolve("bogus").name == DEFAULT_PROFILE


# --- Structural invariants ---------------------------------------------------


def test_profiles_only_reference_registered_tools():
    for profile in [default_registry.resolve(None)]:
        for name in profile.tool_names:
            assert name in TOOL_REGISTRY


def test_prompt_describes_exactly_the_bound_tools():
    profile = default_registry.resolve(None)
    descriptions = profile.tool_descriptions()
    bound = {t.name for t in profile.tools()}
    for name in profile.tool_names:
        assert name in descriptions
    for name in TOOL_REGISTRY:
        if name not in bound:
            assert name not in descriptions


def test_skill_dependencies_reference_registered_tools():
    for skill in all_skills():
        for tool_name in skill.requires:
            assert (
                tool_name in TOOL_REGISTRY
            ), f"skill {skill.name!r} requires unknown tool {tool_name!r}"


def test_skills_only_advertised_when_their_tools_are_bound():
    profile = default_registry.resolve(None)
    bound = set(profile.tool_names)
    for skill in profile.skills():
        assert set(skill.requires) <= bound


def test_default_profile_advertises_core_skills():
    profile = default_registry.resolve(None)
    assert {s.name for s in profile.skills()} == {
        "analyze",
        "capabilities",
        "pull-data",
    }
