"""The two writes a template makes, and the shape of what it records.

Both go through ``dashboard_writer``, which owns the transaction: a section
a reader may only ever see complete must not appear widget by widget.

This module decides one thing of its own — what lands in
``dashboard_sections.config``:

    {"template": <name>, **the template's own record}

The template's name is always there, so a refresh knows which template owns
the section, and a reader is told which period is on screen without reading
a widget's tile layer. By convention a template that covers a period records
``start_date`` and ``end_date`` (see ``base.describe_window``).
"""

from typing import Any

from src.api.repositories import dashboard_writer
from src.api.services.analysis_templates.base import (
    AnalysisTemplate,
    SectionContent,
    TargetGoneError,
    TemplateResult,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _config(
    template: "AnalysisTemplate[Any]", content: SectionContent
) -> dict:
    return {"template": template.entry.name, **content.config}


async def write_section(
    dashboard_id: str,
    template: "AnalysisTemplate[Any]",
    content: SectionContent,
) -> TemplateResult:
    """Write a gathered section onto a dashboard.

    Raises ``TargetGoneError`` when the dashboard was deleted while the
    content was being gathered.
    """
    written = await dashboard_writer.add_section_with_widgets(
        dashboard_id,
        title=content.title,
        description=content.description,
        type=template.entry.name,
        config=_config(template, content),
        widgets=content.widgets,
    )
    if written is None:
        raise TargetGoneError(
            f"Dashboard {dashboard_id} no longer exists, so the "
            f"{template.entry.label} section could not be added."
        )
    section_id, widget_ids = written
    logger.info(
        "analysis_template_section_written",
        template=template.entry.name,
        dashboard_id=str(dashboard_id),
        section_id=section_id,
        widgets=len(widget_ids),
        warnings=len(content.warnings),
    )
    return TemplateResult(
        template=template.entry.name,
        section_id=section_id,
        widget_ids=widget_ids,
        summary=content.summary,
        warnings=content.warnings,
    )


async def replace_section(
    section_id: str,
    template: "AnalysisTemplate[Any]",
    content: SectionContent,
) -> TemplateResult:
    """Swap a section's whole contents for freshly gathered ones.

    The section row survives, so its id and its place on the dashboard
    hold. Insights the previous widgets showed are deleted once nothing
    points at them: they were this section's own content, for parameters
    the section no longer covers.
    """
    written = await dashboard_writer.replace_section_widgets(
        section_id,
        title=content.title,
        description=content.description,
        config=_config(template, content),
        widgets=content.widgets,
    )
    if written is None:
        raise TargetGoneError(
            f"Section {section_id} no longer exists, so it could not be "
            "rebuilt."
        )
    widget_ids, replaced_insight_ids = written
    await dashboard_writer.delete_unreferenced_insights(replaced_insight_ids)
    logger.info(
        "analysis_template_section_replaced",
        template=template.entry.name,
        section_id=str(section_id),
        widgets=len(widget_ids),
        replaced_insights=len(replaced_insight_ids),
        warnings=len(content.warnings),
    )
    return TemplateResult(
        template=template.entry.name,
        section_id=str(section_id),
        widget_ids=widget_ids,
        summary=content.summary,
        warnings=content.warnings,
    )
