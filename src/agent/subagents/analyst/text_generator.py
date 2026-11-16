"""Independent insight-text generator.

Takes resolved charts (spec + data) and produces the narrative
(`primary_insight`) plus follow-up suggestions, decoupled from how the charts
were built. Grounding is chart data + dataset cautions/presentation only —
never conversation state.

It is a LangChain runnable, so when invoked inside the `generate_insights` tool
it nests as a span in the active Langfuse trace via the ambient
`RunnableConfig`. Callers outside a traced context may pass an explicit `config`.
"""

from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, field_validator

from src.agent.language import DEFAULT_LANGUAGE, language_name
from src.agent.llms import json_reply_instruction, resilient_json_output
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.prompts import WORDING_GUIDE
from src.shared.logging_config import get_logger
from src.shared.text_sanitize import strip_control_chars

logger = get_logger(__name__)


class InsightText(BaseModel):
    """The text stage's answer: the narrative and its follow-ups."""

    primary_insight: str = Field(
        description="Overall insight that ties the chart(s) together (2-3 sentences)"
    )
    follow_up_suggestions: List[str] = Field(
        description="1-2 follow-up suggestions based on the available data"
    )

    @field_validator("primary_insight")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # The reply is validated here, not by a response schema, so "present
        # but empty" has to be rejected explicitly (and is then retried).
        if not value.strip():
            raise ValueError("primary_insight must not be blank")
        return value


# The JSON mime type guarantees valid JSON, not its shape, so the keys are
# spelled out in the prompt. Kept as a constant for scripts/probe_gemini_nul.py.
JSON_REPLY_INSTRUCTION = json_reply_instruction(InsightText)

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

{wording_guide}

{reply_format}"""

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
).partial(reply_format=JSON_REPLY_INSTRUCTION)


class InsightTextGenerator:
    """Generates insight text from resolved charts."""

    def __init__(self, model=None):
        # Not `with_structured_output`: Gemini's schema-constrained decoding
        # intermittently replaces accented characters with control characters
        # ("Piau\u0000"), in roughly 1 of 5 answers in our probe runs. The JSON
        # mime type without a schema did not (0 of 300).
        # `resilient_json_output` requests JSON that way and also keeps the
        # retry and fallback policy of the other model calls made from tools.
        self._chain = (
            _PROMPT | resilient_json_output(InsightText, model)
        ).with_config(run_name="generate_insight_text")

    async def generate(
        self,
        charts: List[InsightChart],
        dataset: dict,
        query: str = "",
        executor_context: Optional[str] = None,
        language: str = DEFAULT_LANGUAGE,
        config: Optional[RunnableConfig] = None,
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
        inputs = {
            "wording_guide": WORDING_GUIDE,
            "language": language_name(language),
            **data,
        }
        raw: InsightText = await self._chain.ainvoke(inputs, config=config)
        # Strip any control character the model wrote, and log it, so the text
        # the agent and the user see is the same text that gets stored.
        result = InsightText(
            primary_insight=strip_control_chars(
                raw.primary_insight,
                field="text_stage.primary_insight",
                extra={"language": language},
            ),
            follow_up_suggestions=[
                strip_control_chars(
                    s,
                    field="text_stage.follow_up_suggestion",
                    extra={"language": language},
                )
                for s in raw.follow_up_suggestions
            ],
        )
        logger.info(
            f"Generated insight text ({len(result.primary_insight)} chars, "
            f"{len(result.follow_up_suggestions)} follow-ups)"
        )
        return result
