from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List

import pandas as pd
import tiktoken
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
encoder = tiktoken.get_encoding(
    "o200k_base"
)  # tiktoken encoding for OpenAI's GPT-4o, used for approximate token counting


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
    current_date = datetime.now().strftime("%Y-%m-%d")

    return ChatPromptTemplate.from_messages(
        [
            (
                "user",
                f"""# ROLE
You are the Global Nature Watch's Geospatial Assistant, an expert at analyzing environmental data and creating insightful visualizations.

# CONTEXT
Current date: {current_date}

# TASK
First, evaluate if the provided data can answer the user's query. If not, provide feedback on missing data requirements instead of generating a chart.

If data is sufficient, generate ONE chart insight that best answers the user's query. If the user specifies a chart type (e.g., "show as bar chart", "make this a pie chart"), prioritize that type if appropriate for the data.

# USER QUERY
{{user_query}}

# DATA TO ANALYZE
{{raw_data_prompt}}

# DATASET-SPECIFIC GUIDELINES
{{dataset_guidelines}}

# CRITICAL DATA EVALUATION
**BEFORE PROCEEDING**: Carefully examine if the available data can answer the user's query:

**If data is INSUFFICIENT or MISSING required fields:**
- DO NOT generate any chart insight
- Instead, respond with specific feedback explaining:
  * What exact data/fields are missing for the analysis
  * Which dataset(s) would contain the required information
  * Which region(s) need additional data collection
  * Suggest: "Please select [specific dataset] for [specific region] and pull the data again"

**Only proceed to chart generation if data is SUFFICIENT for the query.**

# CHART TYPE SELECTION
Choose the most appropriate chart type:
- **line**: Time series data, trends over time
- **bar**: Categorical comparisons, rankings
- **stacked-bar**: Show composition within categories (requires series_fields)
- **grouped-bar**: Compare multiple metrics across categories (requires group_field)
- **pie**: Part-to-whole relationships (limit to 6-8 categories max)
- **area**: Cumulative trends, stacked time series
- **scatter**: Show correlations between two variables
- **table**: Detailed data when visualization isn't optimal

# DATA FORMAT REQUIREMENTS
Your chart data MUST follow these rules:
1. **Structure**: Array of objects with simple field names
2. **Field names**: Use clear names like 'date', 'value', 'category', 'year'
3. **Numeric values**: Always numbers, never strings (e.g., 100 not "100")
4. **Date ordering**: Chronological order, not alphabetical
5. **Special formats**:
   - Stacked-bar: [{{{{\"category\": \"2020\", \"metric1\": 100, \"metric2\": 50}}}}] + set series_fields
   - Grouped-bar: [{{{{\"year\": \"2020\", \"type\": \"metric1\", \"value\": 100}}}}] + set group_field

# OUTPUT REQUIREMENTS
Generate exactly:
1. **One chart insight** with:
   - Appropriate chart type for the data
   - Recharts-compatible data array
   - Clear x_axis and y_axis field mappings
   - Insightful title and analysis

2. **1-2 follow-up suggestions** based on available data and capabilities

# CAPABILITIES CONTEXT
You can analyze data for any area of interest, pull data from datasets like {available_datasets} for different time periods, and create various charts/insights. Base follow-ups on what's actually possible with available data and tools.

# LANGUAGE REQUIREMENT
Generate ALL content (insights, titles, follow-ups) in the SAME LANGUAGE as the user query.

# FOLLOW-UP EXAMPLES
- "Show trend over different time period"
- "Compare with nearby [region/area]"
- "Identify top/bottom performers in [metric]"
- "Break down by [relevant category]"
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
        query: Improved query from the user including relevant context that will help in
               better insight generation. Should include specific chart type requests,
               temporal focus, comparison aspects, and any domain-specific context.
        is_comparison: Whether the user is comparing two or more different AOIs (e.g.,
                      comparing Brazil vs Indonesia). Set to False for comparisons within
                      a specific AOI (e.g., provinces in a country, KBAs in a region, counties in a state).
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

    raw_data_prompt = "## RAW DATA FOR ANALYSIS\n\n"

    if is_comparison:
        raw_data_prompt += "**COMPARISON MODE**: Multiple areas/datasets provided for comparative analysis.\n\n"
        for i, data_by_aoi in enumerate(raw_data.values(), 1):
            for j, data in enumerate(data_by_aoi.values(), 1):
                data_copy = data.copy()
                aoi_name = data_copy.pop("aoi_name")
                dataset_name = data_copy.pop("dataset_name")
                data_csv = get_data_csv(data_copy)
                raw_data_prompt += (
                    f"### Dataset {i}.{j}: {aoi_name} - {dataset_name}\n"
                )
                raw_data_prompt += f"```csv\n{data_csv}\n```\n\n"
    else:
        raw_data_prompt += (
            "**SINGLE ANALYSIS MODE**: One area and dataset provided.\n\n"
        )
        # Get the latest key if not comparing
        data_by_aoi = list(raw_data.values())[-1]
        data = list(data_by_aoi.values())[-1]
        data_copy = data.copy()
        aoi_name = data_copy.pop("aoi_name")
        dataset_name = data_copy.pop("dataset_name")
        data_csv = get_data_csv(data_copy)
        raw_data_prompt += f"### Dataset: {aoi_name} - {dataset_name}\n"
        raw_data_prompt += f"```csv\n{data_csv}\n```\n\n"

    dat = {key: len(value) for key, value in raw_data.items()}
    logger.debug(f"Processing data with row counts: {dat}")

    tokens = encoder.encode(raw_data_prompt)
    token_count = len(tokens)
    logger.debug(f"Raw data prompt token count: {token_count}")

    # 24_000 tokens is an approximate window size that would make sure the agent doesn't hallucinate
    if token_count > 23_000:
        return Command(
            update={
                "raw_data": {},  # reset raw data
                "messages": [
                    ToolMessage(
                        content="I've reached my processing limit - you may have requested a large set of areas or too many data points. I'm clearing the current dataset to prevent errors. To continue your analysis, please start a new chat conversation and re-select your areas and datasets.",
                        tool_call_id=tool_call_id,
                        status="success",
                        response_metadata={"msg_type": "human_feedback"},
                    )
                ],
            }
        )

    dataset_guidelines = state.get("dataset").get("prompt_instructions", "")
    if dataset_guidelines:
        dataset_guidelines = (
            f"**Important guidelines for this dataset:**\n{dataset_guidelines}"
        )
    else:
        dataset_guidelines = "No specific dataset guidelines provided."

    try:
        prompt = _create_insight_generation_prompt()
        chain = prompt | SONNET.with_structured_output(InsightResponse)
        response = await chain.ainvoke(
            {
                "user_query": query,
                "raw_data_prompt": raw_data_prompt,
                "dataset_guidelines": dataset_guidelines,
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
