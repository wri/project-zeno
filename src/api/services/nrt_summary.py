"""The title and description of a near-real-time monitoring section.

A recipe-built section has to say what it shows, because nobody typed a
heading for it. One model call reads the chart rows the deterministic
generator produced and writes both: a short title, and a description that
states the figures a reader would otherwise have to work out from the chart.

Grounding is the chart data plus the dataset's own presentation rules —
never conversation state. Same shape as
``src.agent.subagents.analyst.text_generator``, which does this job for
insights.
"""

from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.language import DEFAULT_LANGUAGE, language_name
from src.agent.llms import SMALL_MODEL
from src.agent.subagents.analyst.charts.model import InsightChart
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

TITLE_MAX_CHARS = 60


class SectionSummary(BaseModel):
    """Structured output of the summary call."""

    title: str = Field(
        description=(
            "Section heading naming the area and the period, at most "
            f"{TITLE_MAX_CHARS} characters. No trailing period."
        )
    )
    description: str = Field(
        description=(
            "Two to four sentences: what the section shows, then the key "
            "figures from the chart data."
        )
    )


_SYSTEM = """You write the heading and the summary of a monitoring section on \
a dashboard. The section shows a chart of disturbance alerts over time, a map \
of those alerts, and satellite imagery of the same area and period.

Write a `title` that names the area and the period, at most \
{title_max_chars} characters.

Write a `description` of two to four sentences: first what the section shows, \
then the figures that matter. Take every figure from the chart data below — \
do not compute new ones, and do not describe the chart mechanics. State the \
unit with every area. Name the confidence tiers the data actually contains.

Follow the dataset's presentation rules below, including any caution they \
require about what the alerts mean.

Write both in {language}, regardless of the language of the data or the \
instructions below."""

_USER = """## Area
{aoi_name}

## Period
{start_date} to {end_date}

## How to describe this dataset
{presentation_instructions}

## Charts (spec + data)
{charts}"""

_PROMPT = ChatPromptTemplate.from_messages(
    [("system", _SYSTEM), ("user", _USER)]
)


def fallback_summary(
    aoi_name: str, start_date: str, end_date: str
) -> SectionSummary:
    """Title and description that need no model call.

    Used when the model is unavailable or returns nothing usable: a section
    with a plain heading is worth building, an aborted build is not. States
    no figures, since the point of the generated text is exactly the figures
    this cannot supply.
    """
    return SectionSummary(
        title=f"Near-real-time monitoring — {aoi_name}",
        description=(
            f"Disturbance alerts for {aoi_name} between {start_date} and "
            f"{end_date}, with a map of the alerts and satellite imagery of "
            "the same period. Alerts indicate potential disturbance, not "
            "confirmed deforestation."
        ),
    )


async def generate_section_summary(
    charts: List[InsightChart],
    *,
    aoi_name: str,
    start_date: str,
    end_date: str,
    presentation_instructions: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
    model=SMALL_MODEL,
) -> SectionSummary:
    """The section's title and description, or the fallback pair.

    Never raises: the summary is the last step of a build whose data is
    already gathered, so a model failure must not lose the section.
    """
    if not charts:
        return fallback_summary(aoi_name, start_date, end_date)

    chain = _PROMPT | model.with_structured_output(SectionSummary)
    inputs = {
        "title_max_chars": TITLE_MAX_CHARS,
        "language": language_name(language or DEFAULT_LANGUAGE),
        "aoi_name": aoi_name,
        "start_date": start_date,
        "end_date": end_date,
        "presentation_instructions": presentation_instructions or "(none)",
        "charts": "\n".join(
            chart.model_dump_json(exclude={"insight"}) for chart in charts
        ),
    }
    try:
        result: SectionSummary = await chain.ainvoke(inputs)
    except Exception as error:
        logger.warning(
            "nrt_section_summary_failed",
            error=str(error),
            aoi_name=aoi_name,
        )
        return fallback_summary(aoi_name, start_date, end_date)

    title = (result.title or "").strip()
    description = (result.description or "").strip()
    if not title or not description:
        logger.warning("nrt_section_summary_empty", aoi_name=aoi_name)
        return fallback_summary(aoi_name, start_date, end_date)
    return SectionSummary(
        title=title[:TITLE_MAX_CHARS], description=description
    )
