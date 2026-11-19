"""The system prompt sections (src/agent/prompts/)."""

import re

import pytest

from src.agent.agent_config import (
    BASE_PROFILE,
    DEFAULT_PROFILE,
    default_registry,
)
from src.agent.graph import get_prompt
from src.agent.prompts import (
    INLINE_SKILLS,
    apply_gates,
    gates,
    section_texts,
)
from src.agent.prompts.tool_descriptions import TOOL_DESCRIPTIONS
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


def test_a_flag_gate_keeps_its_block_only_for_the_flag():
    text = "a\n<!-- flag: f -->\nflag line\n<!-- end -->\nb\n"
    flagged = Availability(
        skills=frozenset(), tools=frozenset(), flags=frozenset({"f"})
    )
    assert apply_gates(text, NONE) == "a\nb\n"
    assert apply_gates(text, flagged) == "a\nflag line\nb\n"


def test_the_work_section_has_the_chart_argument_guidance():
    """The prompt has no tool list and no analyze skill, so the work
    section gives the guidance for the chart argument."""
    guidance = "`generate_insights` `chart`"
    assert guidance in get_prompt(default_registry.resolve(DEFAULT_PROFILE))


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


def test_every_gate_names_a_real_skill_tool_or_flag():
    from src.agent.agent_config import ALL_SPECS, FLAG_TOOL_VARIANTS

    tools = {s.tool.name for s in ALL_SPECS}
    for name, text in section_texts():
        for kind, gate in gates(text):
            if kind == "tool":
                assert gate in tools, (name, gate)
            elif kind == "flag":
                assert gate in FLAG_TOOL_VARIANTS, (name, gate)
            else:
                assert get_skill(gate) is not None, (name, gate)


def test_prompt_has_no_tool_list_and_numbered_sections():
    prompt = get_prompt(default_registry.resolve(DEFAULT_PROFILE))
    assert "<!--" not in prompt
    assert "# Tools" not in prompt
    assert "# Subagents" not in prompt
    headings = re.findall(r"^# (\d+)\. ", prompt, flags=re.MULTILINE)
    assert headings == [str(n) for n in range(1, len(headings) + 1)]
    assert "- dashboard:" in prompt
    assert "search_insights" in prompt


def test_prompt_without_skills_drops_skill_and_tool_blocks():
    prompt = get_prompt(default_registry.resolve(BASE_PROFILE))
    assert "Skills" not in prompt
    assert "read_skill" not in prompt
    assert "search_insights" not in prompt
    assert "send_nudge" not in prompt
    assert "dashboard" not in prompt


def test_prompt_surface_section_is_numbered_last():
    prompt = get_prompt(
        default_registry.resolve(DEFAULT_PROFILE), page="dashboard"
    )
    assert re.search(r"^# 6\. Current surface$", prompt, flags=re.MULTILINE)


def test_every_profile_binds_the_tool_descriptions():
    for cfg in default_registry.configs():
        tools = {t.name: t for t in cfg.bound_tools()}
        for name, text in TOOL_DESCRIPTIONS.items():
            if name in tools:
                assert tools[name].description == text, (cfg.name, name)


def test_every_skill_has_a_description():
    from src.agent.skills.loader import all_skills

    for skill in all_skills():
        assert skill.description, skill.name


def test_skills_list_is_one_description_line_per_skill():
    cfg = default_registry.resolve(DEFAULT_PROFILE)
    prompt = get_prompt(cfg)
    for skill in cfg.skill_metas():
        line = f"- {skill.name}: {skill.description}\n"
        if skill.name in INLINE_SKILLS:
            assert line not in prompt + "\n"
        else:
            assert line in prompt + "\n"
