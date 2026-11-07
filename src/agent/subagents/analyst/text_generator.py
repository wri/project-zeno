"""Independent insight-text generator.

Takes resolved charts (spec + data) and produces the narrative
(`primary_insight`) plus follow-up suggestions, decoupled from how the charts
were built. Grounding is chart data + dataset cautions/presentation only —
never conversation state.

It is a LangChain runnable, so when invoked inside the `generate_insights` tool
it nests as a span in the active Langfuse trace via the ambient
`RunnableConfig`. Callers outside a traced context may pass an explicit `config`.
"""

import re
from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda
from pydantic import BaseModel, Field, ValidationError

from src.agent.language import DEFAULT_LANGUAGE, language_name
from src.agent.llms import SMALL_MODEL
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


# Appended to the system prompt: the JSON mime type guarantees valid JSON, not
# its shape, so the keys are spelled out. No braces, so it is safe in a template.
JSON_REPLY_INSTRUCTION = """Reply with a single JSON object and nothing else, \
with exactly these keys: "primary_insight" (a string) and \
"follow_up_suggestions" (an array of strings). Do not wrap it in code fences."""

_SYSTEM = (
    """You write the narrative insight for one or two charts that have \
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

"""
    + JSON_REPLY_INSTRUCTION
)

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


class InsightTextFormatError(ValueError):
    """The model's reply was not the JSON object the prompt asked for."""


_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _parse_insight_text(message) -> InsightText:
    """Turn the model's reply into an ``InsightText``.

    The reply is requested as JSON through the JSON mime type, without a
    response schema, so the shape is checked here. Code fences are tolerated.
    """
    text = message if isinstance(message, str) else str(message.text)
    try:
        result = InsightText.model_validate_json(
            _CODE_FENCE.sub("", text.strip())
        )
    except ValidationError as exc:
        reason = f"{exc.error_count()} validation error(s)"
        logger.warning(
            "insight_text_format_error", reason=reason, length=len(text)
        )
        raise InsightTextFormatError(reason) from exc
    if not result.primary_insight.strip():
        logger.warning(
            "insight_text_format_error", reason="empty", length=len(text)
        )
        raise InsightTextFormatError("primary_insight is empty")
    return result


class InsightTextGenerator:
    """Generates insight text from resolved charts."""

    def __init__(self, model=SMALL_MODEL):
        # Not `with_structured_output`: Gemini's schema-constrained decoding
        # intermittently replaces accented characters with control characters
        # ("Piau\u0000"), in roughly 1 of 5 answers in our probe runs. The JSON
        # mime type without a schema did not (0 of 300). The reply is parsed
        # and validated here, and one malformed reply is retried.
        self._chain = (
            (
                _PROMPT
                | model.bind(response_mime_type="application/json")
                | RunnableLambda(_parse_insight_text)
            )
            .with_retry(
                retry_if_exception_type=(InsightTextFormatError,),
                stop_after_attempt=2,
                wait_exponential_jitter=False,
            )
            .with_config(run_name="generate_insight_text")
        )

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
            ),
            follow_up_suggestions=[
                strip_control_chars(
                    s,
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
