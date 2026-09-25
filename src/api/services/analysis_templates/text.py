"""The title and description of a template section.

One small model call writes both from the data, for every template. The
input is the area, the period, the template purpose, the widgets the section
has, the chart data and the dataset presentation rules. The call never
raises: when the model fails or returns empty text, the template's fixed
i18n text is used. A build must not fail after its data is ready.
"""

from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.datasets.config import DATASETS
from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE, language_name
from src.agent.llms import SMALL_MODEL
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.analysis_templates.models import AnalysisTemplate
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

TITLE_MAX_CHARS = 60


class SectionText(BaseModel):
    """Structured output of the text call."""

    title: str = Field(
        description=(
            "Section heading that names the area and the subject, at most "
            f"{TITLE_MAX_CHARS} characters. No trailing period, no markup."
        )
    )
    description: str = Field(
        description=(
            "One to three short sentences: what the section shows, then the "
            "one or two figures that matter most."
        )
    )


_SYSTEM = """You write the title and the description of a section on a \
dashboard. The section was built from data. Be short, descriptive and to the \
point.

`title`: name the area and the subject. At most {title_max_chars} characters. \
No trailing period. No markup.

`description`: one to three short sentences. Say what the section shows, then \
give the one or two figures that matter most. Take each figure from the chart \
data. Do not compute new figures. Give the unit with each area. Plain prose, \
no markup.

Do not add filler, advice or speculation about causes.

Obey the dataset presentation rules below.

Write both in {language}, whatever the language of the input."""

_USER = """## Area
{aoi_name}

## Period
{start_date} to {end_date}

## Purpose of the section
{purpose}

## Widgets in the section
{widgets}

## Dataset presentation rules
{presentation_instructions}

## Charts (spec and data)
{charts}"""

_PROMPT = ChatPromptTemplate.from_messages(
    [("system", _SYSTEM), ("user", _USER)]
)


def rounded(chart: InsightChart) -> InsightChart:
    """A copy of the chart with its numbers rounded, for the prompt only.

    Analytics areas arrive at full float precision, and a model told to
    quote a figure copies all of its digits. The stored chart keeps full
    precision.
    """
    copy = chart.model_copy(deep=True)
    for row in copy.chart_data:
        for key, value in row.items():
            if isinstance(value, float):
                row[key] = round(value, 1 if abs(value) < 100 else None)
    return copy


def _presentation_instructions(template: AnalysisTemplate) -> str:
    rules = [
        f"{record['dataset_name']}: {record['presentation_instructions']}"
        for record in DATASETS
        if record["dataset_id"] in template.dataset_ids()
        and record.get("presentation_instructions")
    ]
    return "\n\n".join(rules) or "(none)"


async def fallback_text(
    template: AnalysisTemplate,
    *,
    aoi_name: str,
    start_date: str,
    end_date: str,
    language: Optional[str],
) -> tuple[str, str]:
    """The template's fixed i18n title and description."""
    values = {
        "aoi_name": aoi_name,
        "start_date": start_date,
        "end_date": end_date,
    }
    title = await t(template.fallback_title_key, language, **values)
    description = await t(
        template.fallback_description_key, language, **values
    )
    return title[:TITLE_MAX_CHARS], description


async def generate_section_text(
    template: AnalysisTemplate,
    *,
    aoi_name: str,
    start_date: str,
    end_date: str,
    widget_summaries: list[str],
    charts: list[InsightChart],
    language: Optional[str],
    model=SMALL_MODEL,
) -> tuple[str, str]:
    """The section's title and description. Never raises."""
    language = language or DEFAULT_LANGUAGE
    inputs = {
        "title_max_chars": TITLE_MAX_CHARS,
        "language": language_name(language),
        "aoi_name": aoi_name,
        "start_date": start_date,
        "end_date": end_date,
        "purpose": template.purpose,
        "widgets": "\n".join(f"- {s}" for s in widget_summaries),
        "presentation_instructions": _presentation_instructions(template),
        "charts": "\n".join(
            rounded(chart).model_dump_json(exclude={"insight", "color_map"})
            for chart in charts
        )
        or "(none)",
    }
    try:
        chain = _PROMPT | model.with_structured_output(SectionText)
        result: SectionText = await chain.ainvoke(inputs)
        title = (result.title or "").strip().rstrip(".").strip()
        description = (result.description or "").strip()
    except Exception as error:
        logger.warning(
            "analysis_template_text_failed",
            template=template.name,
            error=str(error),
        )
        title = description = ""

    if not title or not description:
        logger.warning(
            "analysis_template_text_fallback", template=template.name
        )
        return await fallback_text(
            template,
            aoi_name=aoi_name,
            start_date=start_date,
            end_date=end_date,
            language=language,
        )
    return title[:TITLE_MAX_CHARS].rstrip(), description
