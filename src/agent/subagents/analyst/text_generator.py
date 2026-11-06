"""Independent insight-text generator.

Takes resolved charts (spec + data) and produces the narrative
(`primary_insight`) plus follow-up suggestions, decoupled from how the charts
were built. Grounding is chart data + dataset cautions/presentation only —
never conversation state.

It is a LangChain runnable, so when invoked inside the `generate_insights` tool
it nests as a span in the active Langfuse trace via the ambient
`RunnableConfig`. Callers outside a traced context may pass an explicit `config`.
"""

from typing import List, Optional, Sequence

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from src.agent.language import DEFAULT_LANGUAGE, language_name
from src.agent.llms import SMALL_MODEL
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.place_masker import PlaceMasker
from src.agent.subagents.analyst.prompts import WORDING_GUIDE
from src.shared.logging_config import get_logger
from src.shared.text_sanitize import strip_control_chars

logger = get_logger(__name__)


class InsightText(BaseModel):
    """Structured output of the text stage."""

    primary_insight: str = Field(
        description="Overall insight that ties the chart(s) together (2-3 sentences)"
    )
    follow_up_suggestions: List[str] = Field(
        description="1-2 follow-up suggestions based on the available data"
    )


_SYSTEM = """You write the narrative insight for one or two charts that have \
already been produced from geospatial data. Describe what the data shows — do \
not invent numbers, and do not redescribe the chart mechanics.

If a total, sum, or other statistic appears in "Pre-computed findings from \
code execution", cite that figure exactly — do not recompute or re-derive it \
yourself from the chart data rows. Only compute a figure yourself if it is not \
already present in the pre-computed findings.

Write a 2-3 sentence `primary_insight` grounded in the numbers, and 1-2 \
`follow_up_suggestions`.

Write both in {language} — regardless of what language the query, dataset \
cautions, or presentation instructions below are written in.

{wording_guide}{place_note}"""

# Added to the system prompt only when place names were masked.
PLACE_NOTE = """

Place names appear in the input as tokens such as PLACE_1: the real names \
were withheld. Each token stands for a real place, so write it exactly as \
given, with the same spelling and capitalisation (for example "PLACE_1 lost \
3,600 ha"). Do not translate, explain, abbreviate or invent them."""

_USER = """## User query
{query}

## Pre-computed findings from code execution
{executor_context}

## Dataset cautions
{cautions}

## How to describe this dataset
{presentation_instructions}

## Charts (spec + data)
{charts}"""

_PROMPT = ChatPromptTemplate.from_messages(
    [("system", _SYSTEM), ("user", _USER)]
)


class InsightTextGenerator:
    """Generates insight text from resolved charts."""

    def __init__(self, model=SMALL_MODEL):
        self._chain = (
            _PROMPT | model.with_structured_output(InsightText)
        ).with_config(run_name="generate_insight_text")

    async def generate(
        self,
        charts: List[InsightChart],
        dataset: dict,
        query: str = "",
        executor_context: Optional[str] = None,
        language: str = DEFAULT_LANGUAGE,
        config: Optional[RunnableConfig] = None,
        place_names: Sequence[str] = (),
    ) -> InsightText:
        charts_block = "\n".join(
            c.model_dump_json(exclude={"insight"}) for c in charts
        )
        data = {
            "query": query or "(none provided)",
            "executor_context": executor_context or "(none)",
            "cautions": dataset.get(
                "cautions", "No specific dataset cautions provided."
            ),
            "presentation_instructions": dataset.get(
                "presentation_instructions", "(none)"
            ),
            "charts": charts_block,
        }
        # Gemini Flash sometimes writes a control character in place of an
        # accented one ("Piau\x00" for "Piauí"). Keep the non-ASCII names of
        # the areas of interest out of the prompt so the model never has to
        # copy them, and put the real names back in what it returns. Only
        # those names are masked: chart titles, labels and the user's own
        # words are often in the user's language and must stay readable. The
        # system prompt (wording guide and language name) is left alone too.
        masker = PlaceMasker.for_texts(place_names, *data.values())
        # Mask first: stand-ins are numbered as names are met, so the mapping
        # (and with it the prompt note) is only known afterwards.
        masked = {key: masker.mask(value) for key, value in data.items()}
        inputs = {
            "wording_guide": WORDING_GUIDE,
            "place_note": PLACE_NOTE if masker.mapping else "",
            "language": language_name(language),
            **masked,
        }
        raw: InsightText = await self._chain.ainvoke(inputs, config=config)
        # Anything still corrupt after the restore is a character the model
        # wrote on its own. Strip it here so the text the agent and the user
        # see is the same text that gets stored.
        result = InsightText(
            primary_insight=strip_control_chars(
                masker.unmask(raw.primary_insight),
                field="text_stage.primary_insight",
            ),
            follow_up_suggestions=[
                strip_control_chars(
                    masker.unmask(s),
                    field="text_stage.follow_up_suggestion",
                )
                for s in raw.follow_up_suggestions
            ],
        )
        logger.info(
            f"Generated insight text ({len(result.primary_insight)} chars, "
            f"{len(result.follow_up_suggestions)} follow-ups)"
        )
        return result
