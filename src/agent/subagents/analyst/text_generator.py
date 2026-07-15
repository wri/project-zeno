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
from pydantic import BaseModel, Field

from src.agent.llms import SMALL_MODEL
from src.agent.subagents.analyst.charts.model import InsightChart
from src.agent.subagents.analyst.prompts import WORDING_GUIDE
from src.shared.logging_config import get_logger

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

{wording_guide}"""

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
        config: Optional[RunnableConfig] = None,
    ) -> InsightText:
        charts_block = "\n".join(
            c.model_dump_json(exclude={"insight"}) for c in charts
        )
        inputs = {
            "wording_guide": WORDING_GUIDE,
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
        result: InsightText = await self._chain.ainvoke(inputs, config=config)
        logger.info(
            f"Generated insight text ({len(result.primary_insight)} chars, "
            f"{len(result.follow_up_suggestions)} follow-ups)"
        )
        return result
