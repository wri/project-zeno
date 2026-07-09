"""ToolSpec and ToolCategory — kept in a leaf module to avoid circular imports.

Tool files import from here to declare their SPEC; agent_config.py imports
both ToolSpec (from here) and each tool's SPEC (from tool files).
"""

from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional

from langchain_core.tools import BaseTool

# A prompt-content gate: which skill or tool a piece of prompt text depends
# on, or None for text every profile can serve. The Literal kind lets mypy
# reject a misspelled namespace at the definition site.
Gate = Optional[tuple[Literal["skill", "tool"], str]]


class ToolCategory(str, Enum):
    """The system-prompt heading under which a tool is grouped."""

    PRIMITIVE = "# Tools (primitives — call when you need them)"
    SUBAGENT = "# Subagents (call as tools — each does its own reasoning; just forward the user's intent)"


@dataclass(frozen=True)
class ToolSpec:
    """A tool plus the prompt fragment that teaches the model to use it."""

    tool: BaseTool
    category: ToolCategory
    prompt_fragment: str


@dataclass(frozen=True)
class Availability:
    """What one agent profile can serve, with skill and tool names kept in
    separate namespaces — a bare ``name in available`` check can't tell a
    skill called ``dashboard`` from a tool called ``dashboard``, and prompt
    gating must never conflate the two."""

    skills: frozenset[str]
    tools: frozenset[str]

    def has_skill(self, name: str) -> bool:
        return name in self.skills

    def has_tool(self, name: str) -> bool:
        return name in self.tools

    def allows(self, gate: Gate) -> bool:
        """Whether prompt text behind ``gate`` may be shown to this profile."""
        if gate is None:
            return True
        kind, name = gate
        return name in (self.skills if kind == "skill" else self.tools)


# The bound tool names of the current request's agent profile. Set once per
# request (``fetch_zeno``) and read from inside tools (``read_skill``) that
# need to know what's actually callable, not just what's listed in the
# prompt. Mirrors ``current_user_id`` in ``src.shared.request_context``.
_bound_tool_names: ContextVar[frozenset[str]] = ContextVar(
    "bound_tool_names", default=frozenset()
)


def set_bound_tool_names(names: frozenset[str]) -> None:
    """Bind the tool names available in the current request's agent profile,
    for the remainder of this context."""
    _bound_tool_names.set(names)


def bound_tool_names() -> frozenset[str]:
    """The tool names bound by ``set_bound_tool_names``; empty when unset."""
    return _bound_tool_names.get()
