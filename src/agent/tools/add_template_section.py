"""add_template_section — build a dashboard section from an analysis template.

Runs the same ``apply_template`` as
``POST /api/dashboards/{id}/sections/from-template``: it pulls the data for
the dashboard's first area, makes the template's widgets and writes them as
one new section. The section is a normal section; the other dashboard tools
can edit it. The agent picks a registered template and its arguments; it
does not write its own spec. The dashboard defaults to the one in state or the one the user is
looking at (view_context). Owner-only.
"""

import json
from typing import Annotated, Any, Dict, Literal, Optional

import structlog
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import ValidationError

from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.common import (
    dashboard_updated_command,
    error_command,
    load_editable_dashboard,
    require_current_user_id,
    resolve_dashboard_id,
)
from src.api.services.analysis_templates.builder import (
    TemplateError,
    apply_template,
)
from src.api.services.analysis_templates.models import AnalysisTemplate
from src.api.services.analysis_templates.registry import (
    TEMPLATES,
    get_template,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Do not name a tool parameter `args`: pydantic's validate_arguments reserves
# it for *args, so LangChain renames it `v__args` and types it as an array
# without `items`, which Gemini rejects.
# The model sees the valid names in the tool schema. Built from the
# registry at import time, which mypy cannot check.
TemplateName = Literal[tuple(template.name for template in TEMPLATES)]  # type: ignore[valid-type]


@tool("add_template_section")
async def add_template_section(
    template: TemplateName,  # type: ignore[valid-type]
    template_args: Optional[Dict[str, Any]] = None,
    dashboard_id: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Build a new dashboard section from an analysis template.

    `template` is the name of a registered template. `template_args` are the
    arguments of that template; a missing argument gets its default.
    `dashboard_id` defaults to the dashboard in state or the one the user is
    currently viewing. The dashboard must have an area. The build takes some
    seconds. The new section is a normal section: change it with the other
    dashboard tools.
    """
    state = state or {}
    user_id = require_current_user_id("add_template_section")

    spec = get_template(template)
    if spec is None:
        return error_command(
            f"Unknown template '{template}'. Use one of: "
            + ", ".join(t.name for t in TEMPLATES)
            + ".",
            tool_call_id,
        )
    try:
        template_args = spec.parse_args(template_args)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or 'args'}: {e['msg']}"
            for e in error.errors(include_url=False)
        )
        return error_command(
            f"Invalid args for template '{spec.name}': {problems}. "
            f"Arguments: {_args_text(spec)}.",
            tool_call_id,
        )

    target_dashboard = resolve_dashboard_id(state, dashboard_id)
    if not target_dashboard:
        return error_command(
            "No dashboard to add the section to. Create one with "
            "create_dashboard, or pass a dashboard_id.",
            tool_call_id,
        )

    logger.info(
        "add_template_section tool called",
        dashboard_id=str(target_dashboard),
        template=spec.name,
        args=template_args.model_dump(mode="json"),
    )

    dashboard = await load_editable_dashboard(
        target_dashboard, "add_template_section"
    )
    if dashboard is None:
        return error_command(
            f"Dashboard {target_dashboard} not found or not editable.",
            tool_call_id,
        )

    try:
        result = await apply_template(
            dashboard,
            spec,
            template_args,
            user_id,
            state.get("language"),
            thread_id=structlog.contextvars.get_contextvars().get("thread_id"),
        )
    except TemplateError as error:
        return error_command(str(error), tool_call_id)

    lines = [
        f"Added section '{result.title}' ({result.section_id}) with "
        f"{len(result.widget_ids)} widgets to dashboard '{dashboard.name}' "
        f"({dashboard.id}), from template '{spec.name}' "
        f"(args {json.dumps(template_args.model_dump(mode='json'))}).",
        f"Description: {result.description}",
    ]
    lines += [f"Warning: {warning}" for warning in result.warnings]
    return dashboard_updated_command(
        dashboard.id, dashboard.name, "\n".join(lines), tool_call_id
    )


_LIMITS = {
    "minimum": ">=",
    "maximum": "<=",
    "exclusiveMinimum": ">",
    "exclusiveMaximum": "<",
}


def _args_text(template: AnalysisTemplate) -> str:
    """One line per template argument, from its JSON schema, e.g.
    "days (integer, >=1, <=365, default 14): Length of the period"."""
    properties = template.args_model.model_json_schema().get("properties", {})
    parts = []
    for name, schema in properties.items():
        facts = [schema.get("type", "any")]
        facts += [
            f"{op}{schema[key]}"
            for key, op in _LIMITS.items()
            if key in schema
        ]
        if "default" in schema:
            facts.append(f"default {json.dumps(schema['default'])}")
        text = f"{name} ({', '.join(facts)})"
        if schema.get("description"):
            text += f": {schema['description'].rstrip('.')}"
        parts.append(text)
    return "; ".join(parts) or "none"


def _template_lines() -> str:
    return "\n".join(
        f"  - '{t.name}': {t.purpose} Args: {_args_text(t)}."
        for t in TEMPLATES
    )


SPEC = ToolSpec(
    tool=add_template_section,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment=(
        "- add_template_section(template, template_args?, dashboard_id?): build a "
        "complete dashboard section from an analysis template, for the "
        "dashboard's area. Dashboard defaults to the one in state or on "
        "screen. Templates:\n" + _template_lines()
    ),
)
