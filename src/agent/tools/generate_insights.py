import re
from typing import Annotated, Dict, List, Optional

import pandas as pd
import structlog
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.agent.llms import GEMINI_FLASH
from src.agent.prompts import WORDING_INSTRUCTIONS
from src.agent.tools.code_executors import GeminiCodeExecutor
from src.agent.tools.code_executors.base import PartType
from src.agent.tools.datasets_config import DATASETS
from src.api.data_models import InsightChartOrm, InsightOrm
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _get_available_datasets() -> str:
    """Get a concise list of available datasets from the datasets configuration."""
    dataset_names = []
    for dataset in DATASETS:
        dataset_names.append(dataset["dataset_name"])

    return ", ".join(dataset_names)


def prepare_dataframes(
    statistics: list[dict],
) -> tuple[List[tuple[pd.DataFrame, str]], List]:
    """
    Prepare DataFrames from raw data for code executor.
    """
    dataframes = []
    source_urls = []

    for data in statistics:
        if not data:
            continue

        df = pd.DataFrame(data["data"])
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
        source_urls.append(data["source_url"])

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
        if file_index < len(source_urls):
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
        if file_index < len(source_urls):
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
    code_instructions: str | None = None,
    context_layer: str | None = None,
) -> str:
    """
    Build the analysis prompt for the code executor.

    Args:
        query: User's analysis query
        file_references: Executor-specific file reference section
        dataset_guidelines: Dataset-specific instructions for metric selection
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

    prompt = f"""### User Query:
{query}


You have access to the following datasets (read-only):
{file_references}

For your text output , don't use first person, but imperative or neutral language.

For example: "I will begin by loading and examining" -> "Load and examine"
---
{guidelines_section}
{dataset_rules_section}

### STEP-BY-STEP WORKFLOW (follow in order):

**STEP 1: ANALYZE THE DATA**
- Load the relevant dataset(s) using pandas.
- Always use the pattern `df = pd.read_csv("input_file_{{i}}.csv")` to load the data, do not assign the file name to a variable first.
- If multiple files represent the same dataset with different parameters (shown in brackets in the file name, e.g. `[canopy_cover=50]`), treat each as a separate series and use the parameter value as the series label.
- Print which dataset(s) you are using (name, date range, and any filtering parameters)
- Explore the data structure, columns, and data types
- Calculate key statistics relevant to the user query
- Print your key findings clearly
- Do **NOT** create any plots or charts yet

**STEP 2: SUMMARIZE INSIGHTS**
- Summarize the data relevant to the user query
- Identify the most important patterns, trends, or comparisons
- Print a clear summary of what the data shows
- Include contextual layers or parameters used for analysis on the datasets

**STEP 3: GENERATE CHART DATA**
Now prepare the data for visualization in Recharts.js:

   a) **CHART TYPE SELECTION** - Choose the most appropriate chart type:
      - **line**: Time series data, trends over time (supports multi-series)
      - **bar**: Categorical comparisons, rankings (supports multi-series for grouped bars)
      - **stacked-bar**: Show composition within categories (use wide format with multiple metric columns)
      - **grouped-bar**: Compare multiple metrics side-by-side (use long format with group column)
      - **pie**: Part-to-whole relationships (limit to 6-8 categories max)
      - **area**: Cumulative trends, stacked time series (supports multi-series)
      - **scatter**: Show correlations between two variables
      - **table**: Detailed data when visualization isn't optimal

   b) **CREATE CHART DATA** following these requirements:
      1. **Structure**: Array of objects (rows) with simple field names as columns
      2. **Field names**: Use clear, lowercase names like 'date', 'value', 'category', 'year', 'count'
      3. **Numeric values**: Always numbers, never strings (e.g., 100 not "100")
      4. **Date ordering**: Chronological order for time series, not alphabetical
      5. **Data format by chart type**:
         - **Single-series line/bar**: [{{"date": "2020-01", "value": 100}}]
           → One metric column, use y_axis="value"

         - **Multi-series line/bar/area**: [{{"year": "2020", "metric1": 100, "metric2": 50}}]
           → Multiple metric columns in WIDE format
           → Use series_fields=["metric1", "metric2"], leave y_axis empty

         - **Stacked-bar**: [{{"category": "Region A", "forest": 100, "grassland": 50, "urban": 30}}]
           → Multiple metric columns in WIDE format (same as multi-series)
           → Use series_fields=["forest", "grassland", "urban"], leave y_axis empty
           → Bars will stack vertically to show composition

         - **Grouped-bar**: [{{"year": "2020", "metric": "forest_loss", "value": 100}}, {{"year": "2020", "metric": "forest_gain", "value": 50}}]
           → LONG format with a grouping column
           → Use group_field="metric", y_axis="value"
           → Bars will appear side-by-side for comparison

         - **Pie**: [{{"name": "Category A", "value": 100}}]
           → Limited to 6-8 slices, use x_axis="name", y_axis="value"

   c) **SAVE THE DATA**: Save the DataFrame as `chart_data.csv` with column names for the frontend. This
   is ABSOLUTELY CRITICAL. Always save the data to a file with the name `chart_data.csv`.
   Do not replace chart_data.csv with a markdown table; the pipeline only reads the CSV artifact.
   The final code execution step must call ...to_csv('chart_data.csv', index=False) with that exact path.
   This is also true for table chart type, always store the output to a file!

   d) **PRINT CHART TYPE**: Clearly state your recommended chart type in the output

**STEP 4: FINAL DATA-DRIVEN INSIGHT**
- Provide a concise, data-driven insight (2-3 sentences)
- Focus on what the data reveals and why it matters
- Base this on the actual numbers and patterns you found
"""

    return prompt


class ChartInsight(BaseModel):
    """
    Represents a chart-based insight with Recharts-compatible data.
    """

    title: str = Field(description="Clear, descriptive title for the chart")
    chart_type: str = Field(
        description="Chart type: 'line', 'bar', 'stacked-bar', 'grouped-bar', 'pie', 'area', 'scatter', or 'table'"
    )
    x_axis: str = Field(
        description="Name of the field to use for X-axis (for applicable chart types)"
    )
    y_axis: str = Field(
        description="Name of the field to use for Y-axis (for applicable chart types)"
    )
    color_field: str = Field(
        default="",
        description="Optional field name for color grouping/categorization",
    )
    stack_field: str = Field(
        default="",
        description="Field name for stacking data (for stacked-bar charts)",
    )
    group_field: str = Field(
        default="",
        description="Field name for grouping bars (for grouped-bar charts)",
    )
    series_fields: List[str] = Field(
        default=[],
        description="List of field names for multiple data series (for multi-bar charts)",
    )


class MultiChartInsight(BaseModel):
    """
    Represents multiple chart-based insights from a single analysis.
    Used when the data supports multiple visualizations (e.g., tree cover loss AND emissions).
    """

    charts: List[ChartInsight] = Field(
        min_length=1,
        max_length=2,
        description="List of 1-2 charts to display, each with title, type, and field mappings",
    )
    primary_insight: str = Field(
        description="Overall insight that ties all charts together (2-3 sentences)"
    )
    follow_up_suggestions: List[str] = Field(
        description="List of 1-2 follow-up suggestions based on available data and capability"
    )


@tool("generate_insights")
async def generate_insights(
    query: str,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """
    Analyzes raw data and generates a single chart insight with Recharts-compatible data.

    This tool analyzes the raw data and generates the most compelling visualization that
    answers the user's query, along with follow-up suggestions for further exploration.

    Args:
        query: Improved query from the user including relevant context that will help in
               better insight generation. Should include specific chart type requests,
               temporal focus, comparison aspects, and any domain-specific context.
    """
    logger.info("GENERATE-INSIGHTS-TOOL")
    logger.debug(f"Generating insights for query: {query}")

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

    statistics = state["statistics"]

    # 1. PREPARE DATAFRAMES: Convert raw_data to DataFrames
    dataframes, source_urls = prepare_dataframes(statistics)
    logger.info(f"Prepared {len(dataframes)} dataframes for analysis")

    # 2. EXTRACT DATASET GUIDELINES: Get dataset-specific instructions early
    dataset = state.get("dataset") or {}
    # For tiered datasets, code_instructions replaces the code-relevant parts of
    # prompt_instructions — skip the legacy blob to avoid redundancy.
    code_instructions = dataset.get("code_instructions")
    dataset_guidelines = (
        "" if code_instructions else dataset.get("prompt_instructions", "")
    )

    # 3. INITIALIZE EXECUTOR: Create Gemini code executor
    executor = GeminiCodeExecutor()

    # 4. BUILD PROMPT: Create analysis prompt with executor-specific file references
    file_references = executor.build_file_references(dataframes)
    analysis_prompt = build_analysis_prompt(
        query,
        file_references,
        dataset_guidelines=dataset_guidelines,
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
    available_datasets = _get_available_datasets()
    # Prefer presentation_instructions (tiered PoC) over prompt_instructions (legacy blob)
    dataset_guidelines = (
        dataset.get("presentation_instructions")
        or dataset.get("prompt_instructions")
        or "No specific dataset guidelines provided."
    )
    dataset_cautions = dataset.get(
        "cautions", "No specific dataset cautions provided."
    )

    # Build dataset list
    dataset_list = "\n".join(
        [f"- {display_name}" for _, display_name in dataframes]
    )

    chart_insight_prompt = f"""Generate structured chart metadata from the analysis output below.

### User Query
{query}

### Available Datasets (only a subset of these was used in the analysis)
{dataset_list}

### Analysis Output (includes recommended chart type)
{text_output}

### Chart Data Preview (first 5 rows)
{chart_data_df.head().to_csv(index=False)}
Total rows: {len(chart_data_df)}

### Dataset Context
Guidelines: {dataset_guidelines}
Cautions: {dataset_cautions}

### Requirements
1. **Language**: Generate ALL content in the SAME LANGUAGE as the user query
2. **Multiple Charts + Data Constraint**: Generate 1-2 complementary charts
   only when both can be built from the SAME shared `chart_data` table
   (same rows/grain), using exact existing column names in chart fields.
   Otherwise, generate exactly 1 chart.
3. **Data Format**: Generate structure in Recharts.js data format - specify field names that map to the chart data columns
4. **Narrative Placement**: Put narrative text ONLY at top-level: `primary_insight` and `follow_up_suggestions`. Do NOT include narrative fields inside chart objects.

5. **Field Mapping Rules by Chart Type**:

   **Single-series (line/bar/area/scatter):**
   - x_axis: Column name for X-axis (e.g., 'year', 'date', 'category')
   - y_axis: Column name for Y-axis (e.g., 'value', 'count')
   - series_fields: [] (empty)
   - group_field: "" (empty)

   **Multi-series line/bar/area (WIDE format):**
   - x_axis: Column name for X-axis (e.g., 'year')
   - y_axis: "" (empty or descriptive label like "Tree Cover Loss (hectares)")
   - series_fields: List of metric column names (e.g., ['jharkhand_loss', 'odisha_loss'])
   - group_field: "" (empty)

   **Stacked-bar (WIDE format):**
   - x_axis: Column name for categories (e.g., 'region', 'year')
   - y_axis: "" (empty or descriptive label)
   - series_fields: List of metric column names to stack (e.g., ['forest', 'grassland', 'urban'])
   - group_field: "" (empty)

   **Grouped-bar (LONG format):**
   - x_axis: Column name for X-axis (e.g., 'year')
   - y_axis: Column name for values (e.g., 'value', 'hectares')
   - series_fields: [] (empty)
   - group_field: Column name for grouping (e.g., 'metric', 'type')

   **Pie:**
   - x_axis: Column name for categories (e.g., 'name', 'category')
   - y_axis: Column name for values (e.g., 'value', 'count')
   - series_fields: [] (empty)
   - group_field: "" (empty)

6. **Follow-ups**: Pick 1-2 suggestions from the capabilities below that are most relevant to the query:
   - Analyze a different or nearby area
   - Pull data from other available datasets: {available_datasets}
   - Show trend over a different time period
   - Compare results at a different parameter value (e.g. a different canopy cover threshold or context layer)
   - Break down by category or identify top performers

{WORDING_INSTRUCTIONS}
"""

    chart_insight_response = await GEMINI_FLASH.with_structured_output(
        MultiChartInsight
    ).ainvoke(chart_insight_prompt)

    # 7. BUILD RESPONSE - Support multiple charts
    tool_message = f"Generated {len(chart_insight_response.charts)} chart(s)\n"
    tool_message += (
        f"Key Finding: {chart_insight_response.primary_insight}\n\n"
    )

    for idx, chart in enumerate(chart_insight_response.charts, 1):
        tool_message += f"Chart {idx}: {chart.title}\n"

    tool_message += "\nFollow-up suggestions:"
    for i, suggestion in enumerate(
        chart_insight_response.follow_up_suggestions, 1
    ):
        tool_message += f"\n{i}. {suggestion}"

    # 8. BUILD INLINE STATE (kept for backwards compatibility during migration)
    encoded_parts = result.get_encoded_parts()
    charts_data = []
    for idx, chart in enumerate(chart_insight_response.charts):
        charts_data.append(
            {
                "id": f"chart_{idx}",
                "title": chart.title,
                "type": chart.chart_type,
                "insight": chart_insight_response.primary_insight,
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
            insight_text=chart_insight_response.primary_insight,
            follow_up_suggestions=chart_insight_response.follow_up_suggestions,
            statistics_ids=statistics_ids,
            codeact_types=[p["type"] for p in encoded_parts],
            codeact_contents=[p["content"] for p in encoded_parts],
        )
        session.add(insight_row)
        await session.flush()

        for idx, chart in enumerate(chart_insight_response.charts):
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
        "insight": chart_insight_response.primary_insight,
        "follow_up_suggestions": chart_insight_response.follow_up_suggestions,
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
