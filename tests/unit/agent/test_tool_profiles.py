"""Tests for agent tool profiles: gating and prompt/tool consistency."""

from src.agent.skills import all_skills
from src.agent.tool_profiles import (
    DEFAULT_PROFILE,
    EXPERIMENTAL_PROFILE,
    PROFILES,
    TOOL_REGISTRY,
    resolve_profile_name,
    skills_for_profile,
    tool_descriptions_for_profile,
    tools_for_profile,
)


def test_resolve_profile_gates_on_help_test_features():
    assert resolve_profile_name(None) == DEFAULT_PROFILE
    assert resolve_profile_name({}) == DEFAULT_PROFILE
    assert (
        resolve_profile_name({"help_test_features": False}) == DEFAULT_PROFILE
    )
    assert (
        resolve_profile_name({"help_test_features": True})
        == EXPERIMENTAL_PROFILE
    )


def test_experimental_is_a_superset_of_default():
    default = set(PROFILES[DEFAULT_PROFILE])
    experimental = set(PROFILES[EXPERIMENTAL_PROFILE])
    assert default <= experimental


def test_profiles_only_reference_registered_tools():
    for names in PROFILES.values():
        for name in names:
            assert name in TOOL_REGISTRY


def test_unknown_profile_falls_back_to_default():
    assert tools_for_profile("nope") == tools_for_profile(DEFAULT_PROFILE)


def test_prompt_describes_exactly_the_bound_tools():
    """The prompt must mention every bound tool and no unbound one — this is
    the invariant that keeps the prompt from drifting from the tool set."""
    for profile, names in PROFILES.items():
        descriptions = tool_descriptions_for_profile(profile)
        bound = {t.name for t in tools_for_profile(profile)}
        for name in names:
            assert name in descriptions
        # A tool that is registered but not in this profile must not appear.
        for name in TOOL_REGISTRY:
            if name not in bound:
                assert name not in descriptions


def test_skill_dependencies_reference_registered_tools():
    """Every tool a skill declares it requires must exist in the registry,
    or the skill could never be advertised in any profile."""
    for skill in all_skills():
        for tool_name in skill.requires:
            assert (
                tool_name in TOOL_REGISTRY
            ), f"skill {skill.name!r} requires unknown tool {tool_name!r}"


def test_skills_only_advertised_when_their_tools_are_bound():
    for profile, names in PROFILES.items():
        bound = set(names)
        for skill in skills_for_profile(profile):
            assert set(skill.requires) <= bound
        # Skills whose deps are unmet are filtered out.
        unmet = [s for s in all_skills() if not set(s.requires) <= bound]
        advertised = {s.name for s in skills_for_profile(profile)}
        for s in unmet:
            assert s.name not in advertised


def test_default_profile_advertises_all_three_recipes():
    # All three recipes' tool deps are met by the default profile today.
    assert {s.name for s in skills_for_profile(DEFAULT_PROFILE)} == {
        "analyze",
        "capabilities",
        "pull-data",
    }
