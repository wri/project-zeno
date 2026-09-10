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

from src.agent.datasets.config import DATASETS
from src.agent.llms import SMALL_MODEL
from src.agent.subagents.analyst.charts.model import Insight
from src.agent.subagents.analyst.code_executors.base import (
    CHART_TYPES,
    ChartType,
)
from src.agent.subagents.analyst.prompts import WORDING_GUIDE
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_DATASETS_BY_ID = {ds["dataset_id"]: ds for ds in DATASETS}


def _dataset_wording(insight: Insight) -> str:
    """The dataset's own naming rules, resolved from the charts' `dataset_id`.

    A revision rewrites titles and narrative from scratch, so without this the
    reviser is the one generator that never learns how its dataset wants its
    metric named, and it can undo a correct title. Charts already persist the
    id for colour resolution; the same id resolves the wording.

    Returns "" when the insight predates `dataset_id` or the entry carries no
    instructions, which leaves the prompt exactly as it was.
    """
    dataset_id = next(
        (c.dataset_id for c in insight.charts if c.dataset_id is not None),
        None,
    )
    if dataset_id is None:
        return ""
    dataset = _DATASETS_BY_ID.get(dataset_id) or {}
    # A revision writes both titles and prose, so it needs both sets of rules:
    # titles are governed by `code_instructions` and prose by
    # `presentation_instructions`. Handing over only one leaves the other half
    # of the output unguided.
    sections = [
        dataset.get("code_instructions"),
        dataset.get("presentation_instructions"),
    ]
    body = "\n\n".join(section for section in sections if section)
    if not body:
        return ""
    return f"\n\n# Dataset naming rules\n{body}"


class RevisedChart(BaseModel):
    """The restyled spec for one existing chart (no data, just presentation)."""

    position: int = Field(
        description="Position of the chart being revised; must match the "
        "position of an existing chart so the data can be re-attached."
    )
    title: str = Field(description="Clear, descriptive chart title")
    chart_type: ChartType = Field(
        description=f"One of: {', '.join(CHART_TYPES)}"
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

{wording_guide}{dataset_wording}"""

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
            f"{', '.join(chart.available_columns()) or '(no data)'}"
            for chart in insight.charts
        )

        inputs = {
            "chart_types": ", ".join(CHART_TYPES),
            "wording_guide": WORDING_GUIDE,
            "dataset_wording": _dataset_wording(insight),
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
