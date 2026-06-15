"""Tests for AgentConfig, AgentConfigRegistry, and feature flags."""

from langchain_core.tools import tool

from src.agent.agent_config import (
    DEFAULT_PROFILE,
    AgentConfig,
    AgentConfigRegistry,
    default_registry,
)
from src.agent.skills import all_skills
from src.agent.tool_spec import ToolCategory, ToolSpec

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
    registry.register(AgentConfig("default", specs=()))
    registry.register(AgentConfig("blog", specs=(FAKE_SPEC,)))
    assert registry.resolve("blog").name == "blog"


def test_registry_falls_back_to_default_for_unknown_ff():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default", specs=()))
    assert registry.resolve("bogus").name == DEFAULT_PROFILE


def test_registry_falls_back_to_default_for_none():
    registry = AgentConfigRegistry()
    registry.register(AgentConfig("default", specs=()))
    assert registry.resolve(None).name == DEFAULT_PROFILE


def test_registry_instances_are_isolated():
    registry_a = AgentConfigRegistry()
    registry_a.register(AgentConfig("default", specs=()))
    registry_a.register(AgentConfig("cat", specs=(), system_prompt="Say cat."))

    registry_b = AgentConfigRegistry()
    registry_b.register(AgentConfig("default", specs=()))

    assert registry_a.resolve("cat").name == "cat"
    assert registry_b.resolve("cat").name == DEFAULT_PROFILE


# --- AgentConfig -------------------------------------------------------------


def test_config_tools_returns_bound_tools():
    c = AgentConfig("test", specs=(FAKE_SPEC,))
    assert _fake_tool in c.tools()


def test_config_tool_descriptions_includes_bound_tool():
    c = AgentConfig("test", specs=(FAKE_SPEC,))
    assert "_fake_tool" in c.tool_descriptions()


def test_config_tool_descriptions_excludes_unbound_tool():
    c = AgentConfig("test", specs=())
    assert "_fake_tool" not in c.tool_descriptions()


# --- Structural invariants ---------------------------------------------------


def test_prompt_describes_exactly_bound_tools():
    """Prompt only mentions tools that are actually bound."""
    config = default_registry.resolve(None)
    descriptions = config.tool_descriptions()
    for spec in config.specs:
        assert spec.tool.name in descriptions
    assert "_fake_tool" not in descriptions


def test_skill_dependencies_all_have_tools():
    """Every tool a skill requires must exist in the default config."""
    available = {s.tool.name for s in default_registry.resolve(None).specs}
    for skill in all_skills():
        for tool_name in skill.requires:
            assert tool_name in available, (
                f"skill {skill.name!r} requires {tool_name!r} "
                "which is not in the default config"
            )


def test_skills_only_advertised_when_tools_bound():
    config = default_registry.resolve(None)
    available = {s.tool.name for s in config.specs}
    for skill in config.skills():
        assert set(skill.requires) <= available


def test_default_config_advertises_core_skills():
    config = default_registry.resolve(None)
    assert {s.name for s in config.skills()} == {
        "analyze",
        "capabilities",
        "pull-data",
    }
