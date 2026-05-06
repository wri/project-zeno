from langchain_core.tools import tool

from src.agent.harness.skills import get_skill_body


@tool
def read_skill(name: str) -> str:
    """Load the full body of a skill by name. Skill metadata (name,
    description, when_to_use) is already in the system prompt; call this
    only after committing to use a particular skill."""
    body = get_skill_body(name)
    if body is None:
        return f"skill not found: {name}"
    return body
