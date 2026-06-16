"""ToolSpec and ToolCategory — kept in a leaf module to avoid circular imports.

Tool files import from here to declare their SPEC; agent_config.py imports
both ToolSpec (from here) and each tool's SPEC (from tool files).
"""

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
