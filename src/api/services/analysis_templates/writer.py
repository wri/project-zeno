"""The two writes a template makes, and the shape of what it records.

Both go through ``dashboard_writer``, which owns the transaction: a section
a reader may only ever see complete must not appear widget by widget.

This module decides one thing of its own — what lands in
``dashboard_sections.config``:

    {"template": <name>, "params": {...}, **the template's own record}

Two of those three keys are read by the generic layer and nothing else. The
name says which template owns the section, so a refresh knows what to
re-run. The parameters say what it was built with, so re-running it
unchanged needs nothing from the caller (``base.stored_params``). The rest
is the template's own record, read only by the template that wrote it.
"""

from typing import Any

from pydantic import BaseModel

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
    template: "AnalysisTemplate[Any]",
    content: SectionContent,
    params: BaseModel,
) -> dict:
    return {
        "template": template.entry.name,
        "params": params.model_dump(mode="json"),
        **content.config,
    }


async def write_section(
    dashboard_id: str,
    template: "AnalysisTemplate[Any]",
    content: SectionContent,
    params: BaseModel,
) -> TemplateResult:
    """Write a gathered section onto a dashboard.

    ``params`` are recorded on the section row, so the section can later be
    re-run exactly as it was built. Raises ``TargetGoneError`` when the
    dashboard was deleted while the content was being gathered.
    """
    written = await dashboard_writer.add_section_with_widgets(
        dashboard_id,
        title=content.title,
        description=content.description,
        type=template.entry.name,
        config=_config(template, content, params),
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
    params: BaseModel,
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
        config=_config(template, content, params),
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
