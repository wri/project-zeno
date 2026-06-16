from langchain_core.tools import tool

from src.agent.skills.loader import get_skill_body
from src.agent.tool_spec import ToolCategory, ToolSpec


@tool("read_skill")
def read_skill(name: str) -> str:
    """Load the full body of a skill by name (metadata is in the system prompt)."""
    body = get_skill_body(name)
    if body is None:
        return f"skill not found: {name}"
    return body


SPEC = ToolSpec(
    tool=read_skill,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment="- read_skill(name): load a skill's full workflow — call it once, after you have committed to using that skill.",
)
