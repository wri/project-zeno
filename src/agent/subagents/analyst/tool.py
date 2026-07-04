import asyncio
import re
from base64 import b64encode
from typing import Annotated, Dict, List, Optional

import pandas as pd
import structlog
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.subagents.analyst.charts import (
    Insight,
    InsightChart,
)
from src.agent.subagents.analyst.code_executors import GeminiCodeExecutor
from src.agent.subagents.analyst.code_executors.base import (
    ChartInsight,
    MultiChartInsight,
    PartType,
)
from src.agent.subagents.analyst.prompts import EXECUTOR_WORKFLOW
from src.agent.subagents.analyst.text_generator import InsightTextGenerator
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.agent.tools.pull_data import fetch_statistics_from_url
from src.api.repositories.insight_writer import persist_insight
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


async def _extract_inline_statistics_data(data: dict) -> dict | None:
    inline_data = data.get("data")
    if not inline_data:
        return None
    if isinstance(inline_data, dict) and set(inline_data.keys()) == {"data"}:
        return inline_data["data"]
    return inline_data


async def _load_statistics_data(data: dict) -> dict | None:
    # If data is inline already, return it
    legacy_data = await _extract_inline_statistics_data(data)
    if legacy_data:
        return legacy_data
    # Otherwise, fetch from source URL and re-apply the aoi_id→name mapping so
    # chart labels stay readable (the raw API result doesn't include names).
    source_url = data.get("source_url")
    if source_url:
        raw = await fetch_statistics_from_url(source_url)
        if raw and (mapping := data.get("aoi_id_to_name")):
            raw["name"] = [mapping.get(i, i) for i in raw.get("aoi_id", [])]
        return raw

    return None


async def prepare_dataframes(
    statistics: list[dict],
) -> tuple[List[tuple[pd.DataFrame, str]], List]:
    """
    Prepare DataFrames from raw data for code executor.

    Fetches ID-backed data by source URL, while keeping older inline-data
    thread state working.
    """
    raw_results = await asyncio.gather(
        *[_load_statistics_data(s) for s in statistics]
    )

    dataframes = []
    source_urls = []

    for data, raw_data in zip(statistics, raw_results):
        if not raw_data:
            continue

        df = pd.DataFrame(raw_data)
        if len(df) > 1:
            constants = df.nunique() == 1
            logger.debug(
                f"Dropping constant columns: {list(df.columns[constants])}"
            )
            df = df.drop(columns=df.columns[constants])

        param_parts = []
        if data.get("context_layer"):
            param_parts.append(f"context_layer={data['context_layer']}")
        for param in data.get("parameters") or []:
            values = ", ".join(str(v) for v in param["values"])
            param_parts.append(f"{param['name']}={values}")
        param_suffix = f" [{', '.join(param_parts)}]" if param_parts else ""
        display_name = f"{', '.join(data['aoi_names'])} — {data['dataset_name']} ({data['start_date']} to {data['end_date']}){param_suffix}"
        dataframes.append((df, display_name))
        source_urls.append(data.get("source_url", ""))

        logger.info(f"Prepared: {display_name}")

    return dataframes, source_urls


def _extract_statistics_ids(statistics: list[dict]) -> list[str]:
    return [
        stat["id"]
        for stat in statistics
        if isinstance(stat, dict) and stat.get("id")
    ]


def replace_csv_paths_with_urls(
    code_block: str, source_urls: List[str]
) -> str:
    """
    Replace CSV file paths in code blocks with URL-based data loading.

    This function replaces references to input_file_{i}.csv with code that
    reads data from the corresponding source URL using pd.read_json().

    Args:
        code_block: Code block string that may contain CSV file references
        source_urls: List of source URLs corresponding to input_file_{i}.csv files

    Returns:
        List of code blocks with CSV paths replaced by URL-based loading

    Example:
        Input code: df = pd.read_csv("input_file_0.csv")
        Output code:
            df = pd.DataFrame(pd.read_json("https://analytics.globalnaturewatch.org/...")["data"]["result"])
    """
    # Pattern to match pd.read_csv("input_file_{i}.csv") or pd.read_csv('input_file_{i}.csv')
    # Also handles variations like pd.read_csv( "input_file_0.csv" ) with spaces
    pattern = r'pd\.read_csv\s*\(\s*["\']input_file_(\d+)\.csv["\']\s*\)'

    def replace_match(match):
        file_index = int(match.group(1))
        if file_index < len(source_urls) and source_urls[file_index]:
            url = source_urls[file_index]
            # Replace the entire pd.read_csv(...) call with URL-based loading
            return f'pd.DataFrame(pd.read_json("{url}")["data"]["result"])'
        else:
            # If URL not available, return original match
            logger.warning(
                f"No source URL found for input_file_{file_index}.csv"
            )
            return match.group(0)

    # Replace all occurrences
    code_block = re.sub(pattern, replace_match, code_block)

    # Also handle standalone file references (e.g., "input_file_0.csv" as a string)
    # This is less common but might occur in some contexts
    standalone_pattern = r'["\']input_file_(\d+)\.csv["\']'

    def replace_standalone(match):
        file_index = int(match.group(1))
        if file_index < len(source_urls) and source_urls[file_index]:
            url = source_urls[file_index]
            # Replace with URL string
            return f'"{url}"'
        else:
            logger.warning(
                f"No source URL found for input_file_{file_index}.csv"
            )
            return match.group(0)

    code_block = re.sub(standalone_pattern, replace_standalone, code_block)
    return code_block


def build_analysis_prompt(
    query: str,
    file_references: str,
    dataset_guidelines: str = "",
    dataset_cautions: str = "",
    code_instructions: Optional[str] = None,
    context_layer: Optional[str] = None,
) -> str:
    """
    Build the analysis prompt for the code executor.

    Args:
        query: User's analysis query
        file_references: Executor-specific file reference section
        dataset_guidelines: Dataset-specific instructions for metric selection
        dataset_cautions: Dataset-specific cautions
        code_instructions: Dataset-specific chart type and data shaping rules (tiered PoC)
        context_layer: Active context layer name, if any (e.g. "driver")

    Returns:
        Formatted prompt string
    """
    guidelines_section = ""
    if dataset_guidelines:
        guidelines_section = f"""
### Dataset-Specific Guidelines (IMPORTANT - follow these for metric selection):
{dataset_guidelines}
---
"""

    cautions_section = ""
    if dataset_cautions:
        cautions_section = f"""
### Dataset-Specific Cautions:
{dataset_cautions}
---
"""

    dataset_rules_section = ""
    if code_instructions:
        header = "### DATASET-SPECIFIC RULES (follow these strictly):\n"
        if context_layer:
            header += f"Active context layer: {context_layer}\n"
        dataset_rules_section = f"""
{header}
{code_instructions}

---
"""

    return f"""### User Query:
{query}


You have access to the following datasets (read-only):
{file_references}

For your text output , don't use first person, but imperative or neutral language.

For example: "I will begin by loading and examining" -> "Load and examine"
---
{guidelines_section}
{dataset_rules_section}
{cautions_section}

{EXECUTOR_WORKFLOW}

   Here is the JSON schema for the insight:
   {MultiChartInsight.model_json_schema()}

   Here is the JSON schema for the chart data:
   {ChartInsight.model_json_schema()}
"""


def _error_command(message: str, tool_call_id: Optional[str]) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=message,
                    tool_call_id=tool_call_id,
                    status="error",
                )
            ]
        }
    )


def _encode_parts(parts: list) -> list[dict]:
    return [
        {
            "type": part.type.value,
            "content": b64encode(part.content.encode("utf-8")).decode("utf-8"),
        }
        for part in parts
    ]


def _build_tool_message(insight: Insight, dataset_cautions: str) -> str:
    """Human-feedback message summarizing the generated charts + insight."""
    tool_message = f"Generated {len(insight.charts)} chart(s):\n"
    for idx, chart in enumerate(insight.charts, 1):
        marker = f"[Chart {idx}]"
        tool_message += (
            f"Place {marker} in your reply to represent the chart. Use this exact UUID; do not invent UUIDs."
            f"Title: '{chart.title}'.\n\n"
        )

    if insight.charts:
        chart_data_df = pd.DataFrame(insight.charts[0].chart_data)
        formatted_df = chart_data_df.apply(
            lambda col: (
                col.map(lambda x: f"{x:.4f}".rstrip("0").rstrip("."))
                if pd.api.types.is_float_dtype(col)
                else col
            )
        )
        csv_str = formatted_df.to_csv(index=False)
        if len(csv_str) < 4000:
            tool_message += f"\nChart data CSV:\n{csv_str}"

    if dataset_cautions:
        tool_message += f"\n\nDataset cautions:\n{dataset_cautions}"

    tool_message += "\n\nFollow-up suggestions:"
    for i, suggestion in enumerate(insight.follow_up_suggestions, 1):
        tool_message += f"\n{i}. {suggestion}"
    return tool_message


class Analyst:
    """Insight subagent: turns pulled data into a chart artifact.

    Used as a tool by the orchestrator via `generate_insights`. The pipeline has
    two independent stages: (1) build charts from the pulled data via the LLM
    code executor, and (2) generate the narrative insight text from those
    charts. It then persists the insight + charts and updates state.
    """

    async def _resolve_charts(
        self,
        query: str,
        statistics: list[dict],
        dataset: dict,
    ) -> tuple[Optional[list[InsightChart]], list[dict], Optional[str]]:
        """Build charts via the LLM code executor.

        Returns (charts, encoded_codeact_parts, error_message). On success
        `charts` is non-empty and error is None. On failure `charts` is None and
        a user-facing error message is returned.
        """
        dataframes, source_urls = await prepare_dataframes(statistics)
        logger.info(f"Prepared {len(dataframes)} dataframes for analysis")

        # When a dataset provides code_instructions, use those and drop
        # prompt_instructions to avoid sending overlapping guidance.
        code_instructions = dataset.get("code_instructions")
        dataset_guidelines = (
            "" if code_instructions else dataset.get("prompt_instructions", "")
        )
        dataset_cautions = dataset.get(
            "cautions", "No specific dataset cautions provided."
        )

        executor = GeminiCodeExecutor()
        analysis_prompt = build_analysis_prompt(
            query,
            executor.build_file_references(dataframes),
            dataset_guidelines=dataset_guidelines,
            dataset_cautions=dataset_cautions,
            code_instructions=code_instructions,
            context_layer=dataset.get("context_layer"),
        )
        logger.debug(f"Analysis prompt:\n{analysis_prompt}")

        file_refs = await executor.prepare_dataframes(dataframes)
        result = await executor.execute(analysis_prompt, file_refs)

        text_output = " ".join(
            part.content
            for part in result.parts
            if part.type == PartType.TEXT_OUTPUT
        )
        if result.error:
            logger.error(f"Code execution error: {result.error}")
            return None, [], f"Analysis failed: {result.error}"
        if not result.chart_data:
            logger.error("No chart data generated")
            return (
                None,
                [],
                f"Failed to generate chart data. Feedback:{text_output}",
            )
        if result.insight is None or not result.insight.charts:
            logger.error("No chart insight generated")
            return (
                None,
                [],
                f"Failed to generate chart insight. Feedback:{text_output}",
            )

        # Make code blocks runnable anywhere by swapping CSV paths for URLs.
        for part in result.parts:
            if part.type == PartType.CODE_BLOCK:
                part.content = replace_csv_paths_with_urls(
                    part.content, source_urls
                )

        charts = [
            InsightChart.from_chart_insight(chart, result.chart_data, idx)
            for idx, chart in enumerate(result.insight.charts)
        ]
        return charts, _encode_parts(result.parts), None

    async def analyze(
        self,
        query: str,
        statistics: list[dict],
        dataset: Optional[dict] = None,
        tool_call_id: Optional[str] = None,
    ) -> Command:
        """Analyze pulled data and produce one chart insight."""
        logger.info("ANALYST: generating insight")
        logger.debug(f"Generating insights for query: {query}")
        dataset = dataset or {}
        dataset_cautions = dataset.get(
            "cautions", "No specific dataset cautions provided."
        )

        # STAGE 1: build charts from the pulled data.
        charts, codeact_parts, error = await self._resolve_charts(
            query,
            statistics,
            dataset,
        )
        if error or not charts:
            return _error_command(
                error or "Failed to generate charts.", tool_call_id
            )

        # STAGE 2: generate insight text from the resolved charts.
        text = await InsightTextGenerator().generate(charts, dataset, query)
        insight = Insight(
            charts=charts,
            primary_insight=text.primary_insight,
            follow_up_suggestions=text.follow_up_suggestions,
        ).stamp_insight()

        # PERSIST + STATE.
        ctx = structlog.contextvars.get_contextvars()
        insight_id = await persist_insight(
            insight,
            user_id=ctx.get("user_id"),
            thread_id=ctx.get("thread_id", ""),
            statistics_ids=_extract_statistics_ids(statistics),
            codeact_parts=codeact_parts,
        )
        logger.info(f"Persisted insight to DB: {insight_id}")

        updated_state = {
            "insight_id": insight_id,
            "insight": insight.primary_insight,
            "follow_up_suggestions": insight.follow_up_suggestions,
            "codeact_parts": codeact_parts,
            "charts_data": [c.to_frontend_dict() for c in insight.charts],
            "messages": [
                ToolMessage(
                    content=_build_tool_message(insight, dataset_cautions),
                    tool_call_id=tool_call_id,
                    status="success",
                    response_metadata={"msg_type": "human_feedback"},
                )
            ],
        }
        return Command(update=updated_state)


@tool("generate_insights")
async def generate_insights(
    query: str,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Analyze pulled data and produce one chart insight with follow-up suggestions."""
    if not state or "statistics" not in state:
        error_msg = "No statistics available yet. Please pull data first."
        logger.error(error_msg)
        return _error_command(error_msg, tool_call_id)
    return await Analyst().analyze(
        query,
        statistics=state["statistics"],
        dataset=state.get("dataset") or {},
        tool_call_id=tool_call_id,
    )


SPEC = ToolSpec(
    tool=generate_insights,
    category=ToolCategory.SUBAGENT,
    prompt_fragment="- generate_insights(query): analyst subagent. Turns pulled data into one chart insight with follow-up suggestions. Requires pull_data to have run first.",
)
