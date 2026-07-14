from langchain_core.tools import tool

from src.agent.skills.loader import get_skill, render_body
from src.agent.tool_spec import ToolCategory, ToolSpec, bound_availability
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


@tool("read_skill")
def read_skill(name: str) -> str:
    """Load the full body of a skill by name (metadata is in the system prompt)."""
    skill = get_skill(name)
    if skill is None:
        logger.warning("read_skill: skill not found", skill_name=name)
        return f"skill not found: {name}"
    if not bound_availability().has_skill(name):
        logger.warning(
            "read_skill: skill not declared by this profile",
            skill_name=name,
        )
        return f"skill not found: {name}"
    logger.info("read_skill: loaded skill", skill_name=name)
    return render_body(skill)


SPEC = ToolSpec(
    tool=read_skill,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment="- read_skill(name): load a skill's full workflow — call it once, after you have committed to using that skill.",
)
