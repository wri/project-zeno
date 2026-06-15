"""Tests for agent tool profiles and ProfileRegistry."""

from src.agent.skills import all_skills
from src.agent.tool_profiles import (
    DEFAULT_PROFILE,
    TOOL_REGISTRY,
    Profile,
    ProfileRegistry,
    default_registry,
)

# --- ProfileRegistry ---------------------------------------------------------


def test_registry_resolves_known_ff():
    registry = ProfileRegistry()
    registry.register(Profile("default", ()))
    registry.register(Profile("blog", ("pick_aoi",)))
    assert registry.resolve("blog").name == "blog"


def test_registry_falls_back_to_default_for_unknown_ff():
    registry = ProfileRegistry()
    registry.register(Profile("default", ()))
    assert registry.resolve("bogus").name == DEFAULT_PROFILE


def test_registry_falls_back_to_default_for_none():
    registry = ProfileRegistry()
    registry.register(Profile("default", ()))
    assert registry.resolve(None).name == DEFAULT_PROFILE


def test_registry_instances_are_isolated():
    registry_a = ProfileRegistry()
    registry_a.register(Profile("default", ()))
    registry_a.register(Profile("cat", (), "Say only the word 'cat'."))

    registry_b = ProfileRegistry()
    registry_b.register(Profile("default", ()))

    assert registry_a.resolve("cat").name == "cat"
    assert registry_b.resolve("cat").name == DEFAULT_PROFILE  # not leaked


def test_profile_system_prompt_override():
    p = Profile("cat", (), "Say only the word 'cat'.")
    assert p.system_prompt == "Say only the word 'cat'."


def test_profile_system_prompt_defaults_to_none():
    p = Profile("default", ("pick_aoi",))
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
