from pathlib import Path
from typing import Annotated, Any, Dict, List

import pandas as pd
import yaml
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.utils.llms import SONNET
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def _get_available_datasets() -> str:
    """Get a concise list of available datasets from the analytics_datasets.yml file."""
    try:
        # Get the path to the YAML file relative to this script
        current_dir = Path(__file__).parent
        yaml_path = current_dir / "analytics_datasets.yml"

        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        dataset_names = []
        for dataset in data.get("datasets", []):
            name = dataset.get("dataset_name", "Unknown")
            dataset_names.append(name)

        return ", ".join(dataset_names)

    except Exception:
        # Fallback to hardcoded list if YAML loading fails
        return "DIST-ALERT, Global Land Cover, Tree Cover Loss, and Grasslands"


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
    data: List[Dict[str, Any]] = Field(
        description="Recharts-compatible data array with objects containing key-value pairs"
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


class InsightResponse(BaseModel):
    """
    Contains 1 main chart insight and follow-up suggestions.
    """

    insight: ChartInsight = Field(
        description="The most useful chart insight for the user's query"
    )
    follow_up_suggestions: List[str] = Field(
        description="List of 2-3 follow-up prompt suggestions for additional analysis"
    )


def _create_insight_generation_prompt() -> ChatPromptTemplate:
    """Create the insight generation prompt with dynamic dataset information."""
    available_datasets = _get_available_datasets()

    return ChatPromptTemplate.from_messages(
        [
            (
                "user",
                f"""
You are the Global Nature Watch's Geospatial Assistant that analyzes environmental data and creates insightful visualizations.

Analyze the provided data and generate the most useful chart insight that answers the user's query. If the user requests a specific chart type (e.g., "show as bar chart", "make this a pie chart"), prioritize that chart type if it's appropriate for the data.

Chart types available:
- 'line': Time series/trends
- 'bar': Categorical comparisons
- 'stacked-bar': Composition within categories
- 'grouped-bar': Multiple metrics across categories
- 'pie': Part-to-whole (max 6-8 categories)
- 'area': Cumulative trends
- 'scatter': Correlations
- 'table': Detailed data

Data format requirements:
- Array of objects with simple field names (e.g., 'date', 'value', 'category')
- Numeric values as numbers, not strings
- For stacked-bar: [{{{{\"category\": \"2020\", \"metric1\": 100, \"metric2\": 50}}}}] + set series_fields
- For grouped-bar: [{{{{\"year\": \"2020\", \"type\": \"metric1\", \"value\": 100}}}}] + set group_field
- If dates are present, order those in chronological order (not alphabetically)

User query: {{user_query}}

{{raw_data_prompt}}

Generate:
1. One chart insight with appropriate chart type, Recharts-compatible data, and clear axis fields
2. 1 or 2 simple follow ups to the user query based on the actual data available

Your capabilities: You can analyze data for any area of interest, pull data from datasets like {available_datasets} for different time periods, and create charts/insights. Base follow-ups on what's actually possible with available data and tools.

IMPORTANT: Generate all insights, titles, and follow-up suggestions in the same language used in the user query.

Follow-up examples: "Show trend over different period", "Compare with another [region] near by", "Top/bottom performers in [metric]"
                """,
            ),
        ]
    )


def get_data_csv(raw_data: Dict) -> str:
    """
    Convert the raw data to a CSV string and drop constant columns.
    Only keep first 3 significant digits for numeric values.
    """
    df = pd.DataFrame(raw_data)
    # Only drop constant columns if we have multiple rows
    if len(df) > 1:
        constants = df.nunique() == 1
        df = df.drop(columns=df.columns[constants])
    return df.to_csv(index=False, float_format="%.3g")


@tool("generate_insights")
async def generate_insights(
    query: str,
    is_comparison: bool,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Analyzes raw data and generates a single chart insight with Recharts-compatible data.

    This tool analyzes the raw data and generates the most compelling visualization that
    answers the user's query, along with follow-up suggestions for further exploration.

    Args:
        query: The user's query to guide insight generation and chart type selection.
        is_comparison: Whether the user is comparing two areas of interest.
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

    raw_data_prompt = (
        "Below are raw data csv of one or more aois and datasets\n"
    )
    if is_comparison:
        for data_by_aoi in raw_data.values():
            for data in data_by_aoi.values():
                data_copy = data.copy()
                aoi_name = data_copy.pop("aoi_name")
                dataset_name = data_copy.pop("dataset_name")
                data_csv = get_data_csv(data_copy)
                raw_data_prompt += f"\nCSV data for AOI with name {aoi_name} and dataset with name {dataset_name}:\n\n{data_csv}\n"
    else:
        # Get the latest key if not comparing
        data_by_aoi = list(raw_data.values())[-1]
        data = list(data_by_aoi.values())[-1]
        data_copy = data.copy()
        aoi_name = data_copy.pop("aoi_name")
        dataset_name = data_copy.pop("dataset_name")
        data_csv = get_data_csv(data_copy)
        raw_data_prompt += f"\nCSV data for AOI with name {aoi_name} and dataset with name {dataset_name}:\n\n{data_csv}\n"

    dat = {key: len(value) for key, value in raw_data.items()}
    logger.debug(f"Processing data with row counts: {dat}")

    prompt_instructions = state.get("dataset").get("prompt_instructions", "")

    try:
        prompt = _create_insight_generation_prompt()
        chain = prompt | SONNET.with_structured_output(InsightResponse)
        response = await chain.ainvoke(
            {
                "user_query": query,
                "raw_data_prompt": raw_data_prompt,
                "prompt_instructions": prompt_instructions,
            }
        )

        insight = response.insight
        follow_ups = response.follow_up_suggestions
        logger.debug(
            f"Generated insight: {insight.title} ({insight.chart_type})"
        )
        logger.debug(f"Generated {len(follow_ups)} follow-up suggestions")

        # Format the response message
        message_parts = []

        message_parts.append(f"Title: {insight.title}")
        message_parts.append(f"Key Finding: {insight.insight}")

        # Add follow-up suggestions
        message_parts.append("Follow-up suggestions:")
        for i, suggestion in enumerate(follow_ups, 1):
            message_parts.append(f"{i}. {suggestion}")

        # Store chart data for frontend
        charts_data = [
            {
                "id": "main_chart",
                "title": insight.title,
                "type": insight.chart_type,
                "insight": insight.insight,
                "data": insight.data,
                "xAxis": insight.x_axis,
                "yAxis": insight.y_axis,
                "colorField": insight.color_field,
                "stackField": insight.stack_field,
                "groupField": insight.group_field,
                "seriesFields": insight.series_fields,
            }
        ]

        tool_message = "\n".join(message_parts)

        # Update state with generated insight and follow-ups
        updated_state = {
            "insight": response.model_dump()["insight"],
            "follow_up_suggestions": follow_ups,
            "charts_data": charts_data,
            "insight_count": 1,
        }

        return Command(
            update={
                **updated_state,
                "messages": [
                    ToolMessage(
                        content=tool_message,
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    except Exception as e:
        error_msg = f"Error generating insights: {str(e)}"
        logger.error(error_msg, exc_info=True)
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
