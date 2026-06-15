"""Tests for agent tool profiles: gating and prompt/tool consistency."""

from src.agent.skills import all_skills
from src.agent.tool_profiles import (
    DEFAULT_PROFILE,
    EXPERIMENTAL_PROFILE,
    PROFILES,
    TOOL_REGISTRY,
    get_profile,
    resolve_profile,
)


def test_resolve_profile_defaults_to_default():
    assert resolve_profile().name == DEFAULT_PROFILE
    assert resolve_profile(ff=None).name == DEFAULT_PROFILE


def test_resolve_profile_exact_ff_match():
    assert (
        resolve_profile(ff=EXPERIMENTAL_PROFILE).name == EXPERIMENTAL_PROFILE
    )


def test_resolve_profile_unknown_ff_falls_back_to_default():
    assert resolve_profile(ff="bogus").name == DEFAULT_PROFILE
    assert resolve_profile(ff="").name == DEFAULT_PROFILE


def test_experimental_is_a_superset_of_default():
    default = set(PROFILES[DEFAULT_PROFILE].tool_names)
    experimental = set(PROFILES[EXPERIMENTAL_PROFILE].tool_names)
    assert default <= experimental


def test_profiles_only_reference_registered_tools():
    for profile in PROFILES.values():
        for name in profile.tool_names:
            assert name in TOOL_REGISTRY


def test_unknown_profile_falls_back_to_default():
    assert get_profile("nope") is PROFILES[DEFAULT_PROFILE]


def test_prompt_describes_exactly_the_bound_tools():
    """The prompt must mention every bound tool and no unbound one — this is
    the invariant that keeps the prompt from drifting from the tool set."""
    for profile in PROFILES.values():
        descriptions = profile.tool_descriptions()
        bound = {t.name for t in profile.tools()}
        for name in profile.tool_names:
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
    for profile in PROFILES.values():
        bound = set(profile.tool_names)
        for skill in profile.skills():
            assert set(skill.requires) <= bound
        # Skills whose deps are unmet are filtered out.
        unmet = [s for s in all_skills() if not set(s.requires) <= bound]
        advertised = {s.name for s in profile.skills()}
        for s in unmet:
            assert s.name not in advertised


def test_default_profile_advertises_all_three_recipes():
    # All three recipes' tool deps are met by the default profile today.
    assert {s.name for s in PROFILES[DEFAULT_PROFILE].skills()} == {
        "analyze",
        "capabilities",
        "pull-data",
    }
