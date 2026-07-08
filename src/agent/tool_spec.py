"""ToolSpec and ToolCategory — kept in a leaf module to avoid circular imports.

Tool files import from here to declare their SPEC; agent_config.py imports
both ToolSpec (from here) and each tool's SPEC (from tool files).
"""

from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum

from langchain_core.tools import BaseTool


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
