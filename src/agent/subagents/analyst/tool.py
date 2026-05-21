import asyncio
import re
from typing import Annotated, Dict, List, Optional

import pandas as pd
import structlog
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.subagents.analyst.code_executors import GeminiCodeExecutor
from src.agent.subagents.analyst.code_executors.base import (
    ChartInsight,
    MultiChartInsight,
    PartType,
)
from src.agent.subagents.analyst.prompts import (
    EXECUTOR_WORKFLOW,
    WORDING_GUIDE,
)
from src.agent.tools.pull_data import fetch_statistics_from_url
from src.api.data_models import InsightChartOrm, InsightOrm
from src.shared.database import get_session_from_pool
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
    code_instructions: str | None = None,
    context_layer: str | None = None,
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

    # Build dataset-specific rules section when tiered code_instructions are available
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

    executor_workflow = EXECUTOR_WORKFLOW
    wording = WORDING_GUIDE

    prompt = f"""### User Query:
{query}


You have access to the following datasets (read-only):
{file_references}

For your text output , don't use first person, but imperative or neutral language.

For example: "I will begin by loading and examining" -> "Load and examine"
---
{guidelines_section}
{dataset_rules_section}
{cautions_section}

{executor_workflow}

   Here is the JSON schema for the insight:
   {MultiChartInsight.model_json_schema()}

   Here is the JSON schema for the chart data:
   {ChartInsight.model_json_schema()}

{wording}
"""

    return prompt


class Analyst:
    """Insight subagent: turns pulled data into a chart artifact.

    Used as a tool by the orchestrator via `generate_insights`. Given the
    pulled `statistics` and the active `dataset`, it builds dataframes, runs
    the code executor (driven by EXECUTOR_WORKFLOW + WORDING_GUIDE), persists
    the resulting insight and charts, and updates state.
    """

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

        # 1. PREPARE DATAFRAMES: Fetch data from source URLs and build DataFrames
        dataframes, source_urls = await prepare_dataframes(statistics)
        logger.info(f"Prepared {len(dataframes)} dataframes for analysis")

        # 2. EXTRACT DATASET GUIDELINES: Get dataset-specific instructions early
        # For tiered datasets, code_instructions replaces the code-relevant parts of
        # prompt_instructions — skip the legacy blob to avoid redundancy.
        code_instructions = dataset.get("code_instructions")
        dataset_guidelines = (
            "" if code_instructions else dataset.get("prompt_instructions", "")
        )
        dataset_cautions = dataset.get(
            "cautions", "No specific dataset cautions provided."
        )
        # 3. INITIALIZE EXECUTOR: Create Gemini code executor
        executor = GeminiCodeExecutor()

        # 4. BUILD PROMPT: Create analysis prompt with executor-specific file references
        file_references = executor.build_file_references(dataframes)
        analysis_prompt = build_analysis_prompt(
            query,
            file_references,
            dataset_guidelines=dataset_guidelines,
            dataset_cautions=dataset_cautions,
            code_instructions=code_instructions,
            context_layer=dataset.get("context_layer"),
        )
        logger.debug(f"Analysis prompt:\n{analysis_prompt}")

        # 4. PREPARE DATA: Convert DataFrames to inline data format
        file_refs = await executor.prepare_dataframes(dataframes)
        logger.info(f"Prepared {len(file_refs)} inline data parts for Gemini")

        # 5. EXECUTE CODE: Run analysis with Gemini
        result = await executor.execute(analysis_prompt, file_refs)

        # Check for errors
        if result.error:
            logger.error(f"Code execution error: {result.error}")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=f"Analysis failed: {result.error}",
                            tool_call_id=tool_call_id,
                            status="error",
                        )
                    ]
                }
            )

        text_output = " ".join(
            [
                part.content
                for part in result.parts
                if part.type == PartType.TEXT_OUTPUT
            ]
        )

        # Check for chart data
        if not result.chart_data:
            logger.error("No chart data generated")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=f"Failed to generate chart data. Feedback:{text_output}",
                            tool_call_id=tool_call_id,
                            status="error",
                        )
                    ]
                }
            )

        if result.insight is None:
            logger.error("No chart insight generated")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=f"Failed to generate chart insight. Feedback:{text_output}",
                            tool_call_id=tool_call_id,
                            status="error",
                        )
                    ]
                }
            )

        logger.info(f"Generated chart data with {len(result.chart_data)} rows")

        # 5.5. REPLACE CSV PATHS: Replace CSV file paths with URL-based loading
        # This makes the code blocks runnable in any environment.
        for part in result.parts:
            if part.type == PartType.CODE_BLOCK:
                part.content = replace_csv_paths_with_urls(
                    part.content, source_urls
                )

        # 6. GENERATE CHART SCHEMA: Use LLM to create structured chart metadata
        chart_data_df = pd.DataFrame(result.chart_data)

        # 7. BUILD RESPONSE - Support multiple charts
        tool_message = f"Generated {len(result.insight.charts)} chart(s)\n"
        tool_message += f"Key Finding: {result.insight.primary_insight}\n\n"

        for idx, chart in enumerate(result.insight.charts, 1):
            tool_message += f"Chart {idx}: {chart.title}\n"

        MAX_CHART_DATA_CHARS_FOR_TOOL_MESSAGE = 4000
        formatted_df = chart_data_df.apply(
            lambda col: col.map(lambda x: f"{x:.4f}".rstrip("0").rstrip("."))
            if pd.api.types.is_float_dtype(col)
            else col
        )
        csv_str = formatted_df.to_csv(index=False)
        if len(csv_str) < MAX_CHART_DATA_CHARS_FOR_TOOL_MESSAGE:
            tool_message += f"\nChart data CSV:\n{csv_str}"

        tool_message += "\nFollow-up suggestions:"
        for i, suggestion in enumerate(
            result.insight.follow_up_suggestions, 1
        ):
            tool_message += f"\n{i}. {suggestion}"

        # 8. BUILD INLINE STATE (kept for backwards compatibility during migration)
        encoded_parts = result.get_encoded_parts()
        charts_data = []
        for idx, chart in enumerate(result.insight.charts):
            charts_data.append(
                {
                    "id": f"chart_{idx}",
                    "title": chart.title,
                    "type": chart.chart_type,
                    "insight": result.insight.primary_insight,
                    "data": result.chart_data,
                    "xAxis": chart.x_axis,
                    "yAxis": chart.y_axis,
                    "colorField": chart.color_field,
                    "stackField": chart.stack_field,
                    "groupField": chart.group_field,
                    "seriesFields": chart.series_fields,
                }
            )

        # 9. PERSIST INSIGHT(S) TO DB
        ctx = structlog.contextvars.get_contextvars()
        statistics_ids = _extract_statistics_ids(statistics)
        insight_ids: list[str] = []
        async with get_session_from_pool() as session:
            insight_row = InsightOrm(
                user_id=ctx.get("user_id"),
                thread_id=ctx.get("thread_id", ""),
                insight_text=result.insight.primary_insight,
                follow_up_suggestions=result.insight.follow_up_suggestions,
                statistics_ids=statistics_ids,
                codeact_types=[p["type"] for p in encoded_parts],
                codeact_contents=[p["content"] for p in encoded_parts],
            )
            session.add(insight_row)
            await session.flush()

            for idx, chart in enumerate(result.insight.charts):
                session.add(
                    InsightChartOrm(
                        insight_id=insight_row.id,
                        position=idx,
                        title=chart.title,
                        chart_type=chart.chart_type,
                        x_axis=chart.x_axis,
                        y_axis=chart.y_axis,
                        color_field=chart.color_field,
                        stack_field=chart.stack_field,
                        group_field=chart.group_field,
                        series_fields=chart.series_fields,
                        chart_data=result.chart_data,
                    )
                )

            await session.commit()
            await session.refresh(insight_row)
            insight_ids.append(str(insight_row.id))

        insight_id = insight_ids[0] if insight_ids else ""
        logger.info(f"Persisted insight to DB: {insight_id}")

        updated_state = {
            "insight_id": insight_id,
            "insight": result.insight.primary_insight,
            "follow_up_suggestions": result.insight.follow_up_suggestions,
            "codeact_parts": encoded_parts,
            "charts_data": charts_data,
            "messages": [
                ToolMessage(
                    content=tool_message,
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
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=error_msg,
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                ]
            }
        )
    return await Analyst().analyze(
        query,
        statistics=state["statistics"],
        dataset=state.get("dataset") or {},
        tool_call_id=tool_call_id,
    )
