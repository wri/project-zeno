"""Guardrails for the skill/tool availability gating.

Prompt content (routing rows, surface sections) is gated on skill and tool
names, so a rename or frontmatter typo would silently drop rows or hide
skills from every profile. These tests turn each of those silent failure
modes into a test failure:

- skill and tool names must never collide (a flat name check would conflate
  them — the bug the Availability split exists to prevent),
- every ROUTING_ROWS gate must resolve to a real skill/tool,
- every skill's ``requires:`` entry must name a tool some profile binds.
"""

from src.agent.agent_config import default_registry
from src.agent.graph import ROUTING_ROWS
from src.agent.skills import all_skills


def _all_registered_tool_names() -> frozenset[str]:
    return frozenset().union(
        *(config.tool_names() for config in default_registry._configs.values())
    )


def test_skill_names_never_collide_with_tool_names():
    """A tool named like a skill would satisfy the wrong gate; keep the
    namespaces disjoint so has_skill/has_tool stay unambiguous."""
    skill_names = {s.name for s in all_skills()}
    collisions = skill_names & _all_registered_tool_names()
    assert (
        not collisions
    ), f"skill names shadow tool names: {sorted(collisions)}"


def test_routing_gates_resolve_to_real_skills_and_tools():
    """A renamed skill/tool must fail here, not silently drop its routing
    row from every prompt."""
    skill_names = {s.name for s in all_skills()}
    tool_names = _all_registered_tool_names()
    for gate, line in ROUTING_ROWS:
        if gate is None:
            continue
        kind, name = gate
        assert kind in ("skill", "tool"), f"unknown gate kind in: {line!r}"
        universe = skill_names if kind == "skill" else tool_names
        assert (
            name in universe
        ), f"routing row gated on unknown {kind} {name!r}: {line!r}"


def test_skill_requires_reference_registered_tools():
    """A typo in a skill's ``requires:`` frontmatter would make the skill
    unavailable in every profile forever, with no signal until a model
    asks for it at runtime."""
    tool_names = _all_registered_tool_names()
    for skill in all_skills():
        unknown = set(skill.requires) - tool_names
        assert not unknown, (
            f"skill {skill.name!r} requires unregistered tools: "
            f"{sorted(unknown)}"
        )
