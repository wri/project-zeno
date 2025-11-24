from typing import Annotated, Dict, List

import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.agents.prompts import WORDING_INSTRUCTIONS
from src.tools.code_executors import GeminiCodeExecutor
from src.tools.datasets_config import DATASETS
from src.utils.llms import GEMINI_FLASH
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def _get_available_datasets() -> str:
    """Get a concise list of available datasets from the datasets configuration."""
    dataset_names = []
    for dataset in DATASETS:
        dataset_names.append(dataset["dataset_name"])

    return ", ".join(dataset_names)


def prepare_dataframes(raw_data: Dict) -> List[tuple[pd.DataFrame, str]]:
    """
    Prepare DataFrames from raw data for code executor.

    Args:
        raw_data: Nested dict of data by AOI and dataset

    Returns:
        List of tuples (DataFrame, display_name)
    """
    dataframes = []
    source_urls = []

    for data_by_aoi in raw_data.values():
        for data in data_by_aoi.values():
            data_copy = data.copy()
            aoi_name = data_copy.pop("aoi_name")
            dataset_name = data_copy.pop("dataset_name")
            start_date = data_copy.pop("start_date")
            end_date = data_copy.pop("end_date")

            # Create DataFrame and drop constant columns
            df = pd.DataFrame(data_copy)
            if len(df) > 1:
                constants = df.nunique() == 1
                logger.debug(
                    f"Dropping constant columns: {list(df.columns[constants])}"
                )
                df = df.drop(columns=df.columns[constants])

            display_name = (
                f"{aoi_name} — {dataset_name} ({start_date} to {end_date})"
            )
            dataframes.append((df, display_name))
            source_urls.append(data["source_url"])

            logger.info(f"Prepared: {display_name}")

    return dataframes, source_urls


def build_analysis_prompt(query: str, file_references: str) -> str:
    """
    Build the analysis prompt for the code executor.

    Args:
        query: User's analysis query
        file_references: Executor-specific file reference section

    Returns:
        Formatted prompt string
    """
    prompt = f"""### User Query:
{query}


You have access to the following datasets (read-only):
{file_references}
---


### STEP-BY-STEP WORKFLOW (follow in order):

**STEP 1: ANALYZE THE DATA**
- Load the relevant dataset(s) using pandas
- Print which dataset(s) you are using (name and date range)
- Explore the data structure, columns, and data types
- Calculate key statistics relevant to the user query
- Print your key findings clearly
- Do **NOT** create any plots or charts yet

**STEP 2: SUMMARIZE INSIGHTS**
- Summarize the data relevant to the user query
- Identify the most important patterns, trends, or comparisons
- Print a clear summary of what the data shows

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

   c) **SAVE THE DATA**: Save the DataFrame as `chart_data.csv` with column names for the frontend

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
    insight: str = Field(
        description="Key insight or finding that this chart reveals (2-3 sentences)"
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
    follow_up_suggestions: List[str] = Field(
        description="List of 1-2 follow-up suggestions based on available data & capability"
    )


@tool("generate_insights")
async def generate_insights(
    query: str,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
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

    if not state or "raw_data" not in state:
        error_msg = "No raw data available in state. Please pull data first."
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

    raw_data = state["raw_data"]

    # 1. PREPARE DATAFRAMES: Convert raw_data to DataFrames
    dataframes, source_urls = prepare_dataframes(raw_data)
    logger.info(f"Prepared {len(dataframes)} dataframes for analysis")

    # 2. INITIALIZE EXECUTOR: Create Gemini code executor
    executor = GeminiCodeExecutor()

    # 3. BUILD PROMPT: Create analysis prompt with executor-specific file references
    file_references = executor.build_file_references(dataframes)
    analysis_prompt = build_analysis_prompt(query, file_references)
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

    # Check for chart data
    if not result.chart_data:
        logger.error("No chart data generated")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Failed to generate chart data. Feedback: {result.text_output}",
                        tool_call_id=tool_call_id,
                        status="error",
                    )
                ]
            }
        )

    logger.info(f"Generated chart data with {len(result.chart_data)} rows")

    # 6. GENERATE CHART SCHEMA: Use LLM to create structured chart metadata
    chart_data_df = pd.DataFrame(result.chart_data)
    available_datasets = _get_available_datasets()
    dataset_guidelines = state.get("dataset").get(
        "prompt_instructions", "No specific dataset guidelines provided."
    )
    dataset_cautions = state.get("dataset").get(
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
{result.text_output}

### Chart Data Preview (first 5 rows)
{chart_data_df.head().to_csv(index=False)}
Total rows: {len(chart_data_df)}

### Dataset Context
Guidelines: {dataset_guidelines}
Cautions: {dataset_cautions}

### Requirements
1. **Language**: Generate ALL content in the SAME LANGUAGE as the user query
2. **Data Format**: Generate structure in Recharts.js data format - specify field names that map to the chart data columns

3. **Field Mapping Rules by Chart Type**:

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

4. **Follow-ups**: Base suggestions on available capabilities - analyze any area, pull data from {available_datasets}, create charts for different time periods
5. **Examples for follow-up suggestions**: "Show trend over different period", "Compare with nearby area", "Identify top performers", "Break down by category"

{WORDING_INSTRUCTIONS}
"""

    chart_insight_response = await GEMINI_FLASH.with_structured_output(
        ChartInsight
    ).ainvoke(chart_insight_prompt)

    # 7. BUILD RESPONSE
    tool_message = f"Title: {chart_insight_response.title}"
    tool_message += f"\nKey Finding: {chart_insight_response.insight}"
    tool_message += "\nFollow-up suggestions:"
    for i, suggestion in enumerate(
        chart_insight_response.follow_up_suggestions, 1
    ):
        tool_message += f"\n{i}. {suggestion}"

    # Store chart data for frontend
    charts_data = [
        {
            "id": "main_chart",
            "title": chart_insight_response.title,
            "type": chart_insight_response.chart_type,
            "insight": chart_insight_response.insight,
            "data": result.chart_data,
            "xAxis": chart_insight_response.x_axis,
            "yAxis": chart_insight_response.y_axis,
            "colorField": chart_insight_response.color_field,
            "stackField": chart_insight_response.stack_field,
            "groupField": chart_insight_response.group_field,
            "seriesFields": chart_insight_response.series_fields,
        }
    ]

    # Update state with generated insight and follow-ups
    updated_state = {
        "insight": chart_insight_response.model_dump()["insight"],
        "follow_up_suggestions": chart_insight_response.model_dump()[
            "follow_up_suggestions"
        ],
        "charts_data": charts_data,
        "text_output": result.text_output,
        "code_blocks": result.code_blocks,
        "execution_outputs": result.execution_outputs,
        "source_urls": source_urls,
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
