from langchain_core.tools import tool

from src.agent.skills.loader import get_skill_body


@tool("read_skill")
def read_skill(name: str) -> str:
    """Load the full body of a skill by name (metadata is in the system prompt)."""
    body = get_skill_body(name)
    if body is None:
        return f"skill not found: {name}"
    return body
