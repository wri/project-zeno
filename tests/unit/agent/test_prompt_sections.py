"""The concise profile's prompt sections (src/agent/prompts/) and the
deferred dashboard tools (docs/concise-agent-plan.md, iteration 2)."""

import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.agent_config import (
    BASE_PROFILE,
    CONCISE_PROFILE,
    CONCISE_REPLIES,
    DEFAULT_PROFILE,
    DEFERRED_SKILL_PAGES,
    DEFERRED_SKILL_TOOLS,
    AgentConfig,
    AgentConfigRegistry,
    default_registry,
)
from src.agent.graph import get_prompt
from src.agent.middleware import DeferredToolsMiddleware
from src.agent.prompts import apply_gates, gates, section_texts
from src.agent.prompts.tool_descriptions import CONCISE_TOOL_DESCRIPTIONS
from src.agent.skills import get_skill
from src.agent.tool_spec import Availability

NONE = Availability(skills=frozenset(), tools=frozenset())
GATED = """a
<!-- tool: t -->
tool line
<!-- end -->
<!-- skill: s -->
skill line
<!-- end -->
b
"""


def test_apply_gates_keeps_only_what_the_profile_serves():
    assert apply_gates(GATED, NONE) == "a\nb\n"
    both = Availability(skills=frozenset({"s"}), tools=frozenset({"t"}))
    assert apply_gates(GATED, both) == "a\ntool line\nskill line\nb\n"


@pytest.mark.parametrize(
    "text",
    [
        "<!-- tool: t -->\nx\n",
        "x\n<!-- end -->\n",
        "<!-- tool: t -->\n<!-- skill: s -->\n<!-- end -->\n",
    ],
)
def test_apply_gates_rejects_bad_blocks(text):
    with pytest.raises(ValueError):
        apply_gates(text, NONE)


def test_every_gate_names_a_real_skill_or_tool():
    from src.agent.agent_config import ALL_SPECS

    tools = {s.tool.name for s in ALL_SPECS}
    for name, text in section_texts():
        for kind, gate in gates(text):
            if kind == "tool":
                assert gate in tools, (name, gate)
            else:
                assert get_skill(gate) is not None, (name, gate)


def test_concise_prompt_has_no_tool_list_and_numbered_sections():
    prompt = get_prompt(default_registry.resolve(CONCISE_PROFILE))
    assert "<!--" not in prompt
    assert "# Tools" not in prompt
    assert "# Subagents" not in prompt
    headings = re.findall(r"^# (\d+)\. ", prompt, flags=re.MULTILINE)
    assert headings == [str(n) for n in range(1, len(headings) + 1)]
    assert "- dashboard:" in prompt
    assert "search_insights" in prompt


def test_concise_prompt_without_skills_drops_skill_and_tool_blocks():
    registry = AgentConfigRegistry()
    registry.register(
        AgentConfig(
            "lean",
            tools=default_registry.resolve(BASE_PROFILE).tools,
            flags=frozenset({CONCISE_REPLIES}),
        )
    )
    prompt = get_prompt(registry.resolve("lean"))
    assert "Skills" not in prompt
    assert "read_skill" not in prompt
    assert "search_insights" not in prompt
    assert "send_nudge" not in prompt
    assert "dashboard" not in prompt


def test_concise_prompt_surface_section_is_numbered_last():
    prompt = get_prompt(
        default_registry.resolve(CONCISE_PROFILE), page="dashboard"
    )
    assert re.search(r"^# 6\. Current surface$", prompt, flags=re.MULTILINE)


def test_concise_profile_binds_the_short_descriptions():
    concise = {
        t.name: t
        for t in default_registry.resolve(CONCISE_PROFILE).bound_tools()
    }
    default = {
        t.name: t
        for t in default_registry.resolve(DEFAULT_PROFILE).bound_tools()
    }
    for name, text in CONCISE_TOOL_DESCRIPTIONS.items():
        assert concise[name].description == text
        assert default[name].description != text
        # The copy keeps the schema and the function of the tool.
        assert concise[name].args == default[name].args


def test_deferred_tools_are_real_dashboard_tools():
    from src.agent.agent_config import ALL_SPECS

    tools = {s.tool.name for s in ALL_SPECS}
    for skill, names in DEFERRED_SKILL_TOOLS.items():
        assert get_skill(skill) is not None
        assert names <= tools
        # Tools other skills call are never deferred.
        assert "send_nudge" not in names
        assert "search_insights" not in names
        assert "inspect_view_context" not in names


def _middleware():
    return DeferredToolsMiddleware(DEFERRED_SKILL_TOOLS, DEFERRED_SKILL_PAGES)


def test_dashboard_tools_hidden_until_the_skill_is_read():
    mw = _middleware()
    asked = [HumanMessage("Create a dashboard for Brazil")]
    assert mw.hidden_tools({}, asked) == DEFERRED_SKILL_TOOLS["dashboard"]

    read = asked + [
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "read_skill",
                    "args": {"name": "dashboard"},
                    "id": "1",
                }
            ],
        )
    ]
    assert mw.hidden_tools({}, read) == frozenset()

    other = asked + [
        AIMessage(
            "",
            tool_calls=[
                {"name": "read_skill", "args": {"name": "analyze"}, "id": "1"}
            ],
        )
    ]
    assert mw.hidden_tools({}, other) == DEFERRED_SKILL_TOOLS["dashboard"]


def test_dashboard_tools_sent_on_the_dashboard_page():
    mw = _middleware()
    state = {"view_context": {"page": "dashboard"}}
    assert mw.hidden_tools(state, []) == frozenset()
    state = {"view_context": {"page": "map"}}
    assert mw.hidden_tools(state, []) == DEFERRED_SKILL_TOOLS["dashboard"]
