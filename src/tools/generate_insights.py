from typing import Annotated, Dict, List

import pandas as pd
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.utils.llms import GEMINI
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class ChartInsight(BaseModel):
    """
    Represents a chart-based insight with metadata for frontend rendering.
    The actual data is passed separately as raw chart_data.
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
        description="List of 2-3 follow-up prompt suggestions for additional analysis"
    )


INSIGHT_GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "user",
            """You are Zeno, an AI assistant that analyzes environmental data and creates insightful visualizations.

Your task: Analyze the provided CSV data and generate chart metadata (title, chart type, field mappings, insights).

The actual data will be passed separately to the frontend - you only need to specify which fields to use for visualization.

<chart_types>
- 'line': Time series/trends over time
- 'bar': Categorical comparisons
- 'stacked-bar': Composition within categories (parts of a whole)
- 'grouped-bar': Multiple metrics across categories
- 'pie': Part-to-whole relationships (max 6-8 categories)
- 'area': Cumulative trends over time
- 'scatter': Correlations between two variables
- 'table': Detailed data display
</chart_types>

<field_mapping_instructions>
1. ANALYZE the CSV data structure and identify column names
2. CHOOSE appropriate chart type based on data characteristics
3. SPECIFY which CSV column names to use for x_axis, y_axis, color_field, etc.
4. WRITE insights based on actual data patterns you observe
5. For stacked-bar: List all numeric columns in series_fields array
6. For grouped-bar: Specify the grouping column in group_field
7. For pie charts: Use categorical column for x_axis, numeric column for y_axis
</field_mapping_instructions>

<field_examples>
CSV columns: "date,alerts,region,country,src,src_id,confidence"
x_axis: "date", y_axis: "alerts", color_field: "region", chart_type: "line"

CSV columns: "country,forest_loss_ha,year,region,src,confidence,data_source"
x_axis: "country", y_axis: "forest_loss_ha", color_field: "region", chart_type: "bar"

CSV columns: "year,agriculture,logging,fires,country,src_id,confidence,region"
x_axis: "year", series_fields: ["agriculture", "logging", "fires"], chart_type: "stacked-bar"

CSV columns: "country,metric,value,year,region,src,confidence,data_source"
x_axis: "country", y_axis: "value", group_field: "metric", chart_type: "grouped-bar"

CSV columns: "cause,percentage,country,year,src,confidence,data_quality"
x_axis: "cause", y_axis: "percentage", chart_type: "pie"

CSV columns: "country,alerts,forest_loss_ha,fires,region,confidence,src,data_source"
chart_type: "table" (no x_axis/y_axis needed - displays raw data with columns: country, alerts, forest_loss_ha, fires, region)

CSV columns: "forest_loss_ha,fire_incidents,country,region,year,src,confidence,data_source"
x_axis: "forest_loss_ha", y_axis: "fire_incidents", color_field: "region", chart_type: "scatter"

FIELD SELECTION GUIDELINES:
- PRIMARY: Choose the most meaningful categorical/temporal field for x_axis
- SECONDARY: Choose the main numeric metric for y_axis
- GROUPING: Use categorical fields like region/country for color_field when helpful
- IGNORE: Metadata fields like src, src_id, lat, lon, data_source, threshold, data_quality
- SERIES: For stacked/grouped charts, select multiple related numeric columns
</field_examples>

User query: {user_query}
Area of interest: {aoi_name}
Raw data (CSV):
{raw_data}

Analyze the data structure and generate appropriate chart metadata with field mappings.""",
        ),
    ]
)


@tool
def generate_insights(
    query: str,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Analyzes raw data and generates a single chart insight with Recharts-compatible data.

    This tool analyzes the raw data and generates the most compelling visualization that
    answers the user's query, along with follow-up suggestions for further exploration.

    Args:
        query: The user's query to guide insight generation and chart type selection.
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
    logger.debug(f"Processing data with {len(raw_data)} rows")

    # Convert data to DataFrame and then to CSV string for the prompt
    raw_data = pd.DataFrame(raw_data)
    data_csv = raw_data.to_csv(index=False)
    logger.debug(f"Data columns: {list(raw_data.columns)}")

    # Generate insights using the LLM
    try:
        chain = INSIGHT_GENERATION_PROMPT | GEMINI.with_structured_output(
            ChartInsight
        )
        insight = chain.invoke(
            {
                "user_query": query,
                "raw_data": data_csv,
                "aoi_name": state.get("aoi_name", ""),
            }
        )

        logger.debug(
            f"Generated insight: {insight.title} ({insight.chart_type})"
        )

        # Convert raw_data to dict format for frontend
        chart_data = raw_data.to_dict("records")
        data_points_count = len(raw_data)

        # Format the response message
        message_parts = []

        message_parts.append(f"**{insight.title}**")
        message_parts.append(f"Chart Type: {insight.chart_type}")
        message_parts.append(f"Key Finding: {insight.insight}")
        message_parts.append(f"Data Points: {data_points_count}")
        message_parts.append("")

        # Add follow-up suggestions
        message_parts.append("**💡 Follow-up suggestions:**")
        for i, suggestion in enumerate(insight.follow_up_suggestions, 1):
            message_parts.append(f"{i}. {suggestion}")
        message_parts.append("")

        # Store chart data for frontend - pass raw data directly
        charts_data = {
            "id": "main_chart",
            "title": insight.title,
            "type": insight.chart_type,
            "insight": insight.insight,
            "data": chart_data,  # Raw data passed directly
            "xAxis": insight.x_axis,
            "yAxis": insight.y_axis,
            "colorField": insight.color_field,
            "stackField": insight.stack_field,
            "groupField": insight.group_field,
            "seriesFields": insight.series_fields,
            "followUpSuggestions": insight.follow_up_suggestions,
        }

        tool_message = "\n".join(message_parts)

        # Update state with generated insight and follow-ups
        updated_state = {
            "charts_data": charts_data,
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


if __name__ == "__main__":
    # Example usage for testing different chart types

    # Test 1: Simple Line Chart - Time series data
    mock_state_line = {
        "raw_data": pd.DataFrame(
            {
                "date": [
                    "2020-01-01",
                    "2021-01-01",
                    "2022-01-01",
                    "2023-01-01",
                ],
                "alerts": [1200, 1450, 1100, 980],
                "region": ["Amazon", "Amazon", "Amazon", "Amazon"],
            }
        )
    }

    result_line = generate_insights.func(
        query="What are the trends in deforestation alerts over time?",
        state=mock_state_line,
        tool_call_id="test-line",
    )

    print("=== Simple Line Chart Test ===")
    print(result_line.update["charts_data"])

    # Test 2: Simple Bar Chart - Categorical comparison
    mock_state_bar = {
        "raw_data": pd.DataFrame(
            {
                "country": ["Brazil", "Indonesia", "DRC", "Peru", "Colombia"],
                "forest_loss_ha": [
                    11568000,
                    6020000,
                    4770000,
                    1630000,
                    1240000,
                ],
                "year": [2022, 2022, 2022, 2022, 2022],
            }
        )
    }

    result_bar = generate_insights.func(
        query="Which countries have the highest forest loss?",
        state=mock_state_bar,
        tool_call_id="test-bar",
    )

    print("\n=== Simple Bar Chart Test ===")
    print(result_bar.update["charts_data"])

    # Test 3: Complex Stacked Bar Chart - Composition data
    mock_state_stacked = {
        "raw_data": pd.DataFrame(
            {
                "year": ["2020", "2021", "2022", "2023"],
                "deforestation": [1200, 1100, 950, 800],
                "fires": [800, 900, 1200, 1100],
                "logging": [400, 350, 300, 250],
                "agriculture": [600, 700, 800, 750],
                "region": ["Amazon", "Amazon", "Amazon", "Amazon"],
            }
        )
    }

    result_stacked = generate_insights.func(
        query="Show me the composition of forest loss causes over time as a stacked bar chart",
        state=mock_state_stacked,
        tool_call_id="test-stacked",
    )

    print("\n=== Complex Stacked Bar Chart Test ===")
    print(result_stacked.update["charts_data"])

    # Test 4: Complex Grouped Bar Chart - Multiple metrics comparison
    mock_state_grouped = {
        "raw_data": pd.DataFrame(
            {
                "country": [
                    "Brazil",
                    "Brazil",
                    "Indonesia",
                    "Indonesia",
                    "DRC",
                    "DRC",
                ],
                "metric": [
                    "Forest Loss",
                    "Fire Incidents",
                    "Forest Loss",
                    "Fire Incidents",
                    "Forest Loss",
                    "Fire Incidents",
                ],
                "value": [11568, 8500, 6020, 4200, 4770, 2100],
                "year": [2022, 2022, 2022, 2022, 2022, 2022],
            }
        )
    }

    result_grouped = generate_insights.func(
        query="Compare forest loss and fire incidents across countries using grouped bars",
        state=mock_state_grouped,
        tool_call_id="test-grouped",
    )

    print("\n=== Complex Grouped Bar Chart Test ===")
    print(result_grouped.update["charts_data"])

    # Test 5: Pie Chart - Part-to-whole relationship
    mock_state_pie = {
        "raw_data": pd.DataFrame(
            {
                "cause": [
                    "Deforestation",
                    "Fires",
                    "Logging",
                    "Agriculture",
                    "Mining",
                ],
                "percentage": [45, 25, 15, 10, 5],
                "region": ["Global", "Global", "Global", "Global", "Global"],
            }
        )
    }

    result_pie = generate_insights.func(
        query="What are the main causes of forest loss globally? Show as pie chart",
        state=mock_state_pie,
        tool_call_id="test-pie",
    )

    print("\n=== Pie Chart Test ===")
    print(result_pie.update["charts_data"])
