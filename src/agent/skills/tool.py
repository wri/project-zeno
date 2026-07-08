from langchain_core.tools import tool

from src.agent.skills.loader import get_skill, get_skill_body
from src.agent.tool_spec import ToolCategory, ToolSpec, bound_tool_names
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


@tool("read_skill")
def read_skill(name: str) -> str:
    """Load the full body of a skill by name (metadata is in the system prompt)."""
    skill = get_skill(name)
    if skill is None:
        logger.warning("read_skill: skill not found", skill_name=name)
        return f"skill not found: {name}"
    missing = set(skill.requires) - bound_tool_names()
    if missing:
        logger.warning(
            "read_skill: skill not available in this profile",
            skill_name=name,
            missing_tools=sorted(missing),
        )
        return f"skill not found: {name}"
    body = get_skill_body(name)
    assert body is not None  # skill exists: confirmed by get_skill above
    logger.info("read_skill: loaded skill", skill_name=name)
    return body


SPEC = ToolSpec(
    tool=read_skill,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment="- read_skill(name): load a skill's full workflow — call it once, after you have committed to using that skill.",
)
