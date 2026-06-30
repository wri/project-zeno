"""Generative insight display reviser.

Rewrites the *presentation* of an existing insight — narrative text, follow-up
suggestions, chart titles, chart types and field mappings — without pulling new
data or running new code. The underlying ``chart_data`` rows are fixed; the
reviser may only restyle the charts and re-map among the columns that already
exist in each chart's data.

Like `InsightTextGenerator`, this is a LangChain runnable, so it nests as a span
in the active Langfuse trace via the ambient `RunnableConfig`.
"""

import json
from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from src.agent.llms import SMALL_MODEL
from src.agent.subagents.analyst.charts.model import Insight
from src.agent.subagents.analyst.prompts import WORDING_GUIDE
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# The chart types the frontend can render (mirrors ChartInsight's description).
ALLOWED_CHART_TYPES = [
    "line",
    "bar",
    "stacked-bar",
    "grouped-bar",
    "pie",
    "area",
    "scatter",
    "table",
]


class RevisedChart(BaseModel):
    """The restyled spec for one existing chart (no data, just presentation)."""

    position: int = Field(
        description="Position of the chart being revised; must match the "
        "position of an existing chart so the data can be re-attached."
    )
    title: str = Field(description="Clear, descriptive chart title")
    chart_type: str = Field(
        description=f"One of: {', '.join(ALLOWED_CHART_TYPES)}"
    )
    x_axis: str = Field(
        default="", description="Existing column for the X-axis"
    )
    y_axis: str = Field(
        default="",
        description="Existing column for the Y-axis (single-series charts)",
    )
    color_field: str = Field(
        default="", description="Existing column for color"
    )
    stack_field: str = Field(
        default="", description="Existing column to stack"
    )
    group_field: str = Field(
        default="", description="Existing column to group"
    )
    series_fields: List[str] = Field(
        default_factory=list,
        description="Existing columns for multi-series charts",
    )


class RevisedInsight(BaseModel):
    """Structured output: the restyled narrative + chart specs."""

    primary_insight: str = Field(
        description="Revised overall insight (2-3 sentences)"
    )
    follow_up_suggestions: List[str] = Field(
        description="Revised 1-2 follow-up suggestions"
    )
    charts: List[RevisedChart] = Field(
        description="One entry per existing chart, keyed by position"
    )


_SYSTEM = """You restyle an existing data insight — its narrative text, \
follow-up suggestions, chart titles, chart types and field mappings.

You are NOT given new data and you MUST NOT invent any: the underlying chart \
rows are fixed. You may only:
- reword the `primary_insight` and `follow_up_suggestions`,
- rename chart titles,
- change a chart's type (one of: {chart_types}),
- re-map a chart to DIFFERENT columns that ALREADY EXIST in its data.

Hard rules:
- Never reference a column that is not listed as available for that chart.
- Return exactly one revised chart per existing chart, keeping its `position`. \
Do not add or remove charts.
- For chart types other than 'pie' and 'table', set either `y_axis` (single \
series) or `series_fields` (multi series).
- Apply only what the instruction asks for; leave everything else as it was.

{wording_guide}"""

_USER = """## Instruction (what to change)
{instruction}

## Current insight
{current}

## Available columns per chart (position -> columns)
{columns}"""

_PROMPT = ChatPromptTemplate.from_messages(
    [("system", _SYSTEM), ("user", _USER)]
)


class InsightDisplayReviser:
    """Generates a restyled insight spec from an existing one + an instruction."""

    def __init__(self, model=SMALL_MODEL):
        self._chain = (
            _PROMPT | model.with_structured_output(RevisedInsight)
        ).with_config(run_name="revise_insight_display")

    async def revise(
        self,
        insight: Insight,
        instruction: str,
        config: Optional[RunnableConfig] = None,
    ) -> RevisedInsight:
        # Show the spec but not the rows — the data is fixed and only inflates
        # the prompt; available columns are surfaced separately below.
        current = json.dumps(
            insight.model_dump(
                exclude={"charts": {"__all__": {"chart_data", "insight"}}}
            ),
            default=str,
        )

        columns = "\n".join(
            f"- {chart.position}: "
            f"{', '.join(chart.chart_data[0].keys()) if chart.chart_data else '(no data)'}"
            for chart in insight.charts
        )

        inputs = {
            "chart_types": ", ".join(ALLOWED_CHART_TYPES),
            "wording_guide": WORDING_GUIDE,
            "instruction": instruction or "(none provided)",
            "current": current,
            "columns": columns,
        }
        result: RevisedInsight = await self._chain.ainvoke(
            inputs, config=config
        )
        logger.info(
            "revised insight display",
            charts=len(result.charts),
            follow_ups=len(result.follow_up_suggestions),
        )
        return result
