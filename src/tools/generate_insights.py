from typing import Annotated, Dict, List

import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

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

            logger.info(f"Prepared: {display_name}")

    return dataframes


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


### Workflow:

1. **Analyze**: Use pandas to extract insights or summarize data relevant to the query. Print key findings clearly. Do **not** create any plots or charts.
2. **Prepare output**:
    - Recommend a suitable chart type for visualization, choose ONE from: line, bar, area, pie, stacked-bar, grouped-bar, table.
    - Create a clean DataFrame for the chart with appropriate columns for the chart type and save it as: `chart_data.csv`.
3. **Summarize**: Provide a data-driven insight based on your analysis at the end.
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

    try:
        # 1. PREPARE DATAFRAMES: Convert raw_data to DataFrames
        dataframes = prepare_dataframes(raw_data)
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

        chart_insight_prompt = f"""Based on analysis done by an expert & data saved for visualization, generate structured response.

### Analysis Output
{result.text_output}

### Saved chart data - head 5 rows
{chart_data_df.head().to_csv(index=False)}

Total rows: {len(chart_data_df)}

### Language Context
Generate ALL content (insights, titles, follow-ups) in the SAME LANGUAGE as the user query.
Dataset specific guidelines: {dataset_guidelines}
Dataset specific cautions: {dataset_cautions}

#### Capability Context
You can analyze data for any area of interest, pull data from datasets like {available_datasets} for different time periods, and create various charts/insights. Base follow-ups on what's actually possible with available data and tools.

#### Language Context
Generate ALL content (insights, titles, follow-ups) in the SAME LANGUAGE as the user query.

#### Follow-up Examples
- "Show trend over different time period"
- "Compare with nearby [region/area]"
- "Identify top/bottom performers in [metric]"
- "Break down by [relevant category]"
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

    except Exception as e:
        logger.error(f"Unexpected error in generate_insights: {e}")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Unexpected error in generate_insights: {e}",
                        tool_call_id=tool_call_id,
                        status="error",
                        response_metadata={"msg_type": "human_feedback"},
                    )
                ],
            }
        )
