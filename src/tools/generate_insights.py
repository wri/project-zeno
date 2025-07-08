from typing import Annotated, Any, Dict, List

import pandas as pd
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.utils.logging_config import get_logger
from src.utils.llms import SONNET

logger = get_logger(__name__)


class ChartInsight(BaseModel):
    """
    Represents a chart-based insight with Recharts-compatible data.
    """

    title: str = Field(description="Clear, descriptive title for the chart")
    chart_type: str = Field(
        description="Chart type: 'line', 'bar', 'pie', 'area', 'scatter', or 'table'"
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


class InsightResponse(BaseModel):
    """
    Contains 1-2 chart insights generated from the data.
    """

    insights: List[ChartInsight] = Field(
        description="List of 1-2 chart insights, ordered by importance"
    )


INSIGHT_GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "user",
            """
You are Zeno, an AI assistant that analyzes environmental data and creates insightful visualizations.

Your task is to analyze the provided raw data and generate 1-2 compelling chart insights that answer the user's query.

For each insight, you need to:
1. Choose the most appropriate chart type based on the data characteristics
2. Transform the data into Recharts-compatible format (array of objects)
3. Provide a clear title and key insight
4. Specify axis fields for the chart

Chart type guidelines:
- 'line': For time series or continuous data trends
- 'bar': For categorical comparisons or rankings
- 'pie': For part-to-whole relationships (max 6-8 categories)
- 'area': For cumulative data or filled trends
- 'scatter': For correlation between two variables
- 'table': For detailed data that doesn't visualize well

Recharts data format:
- Array of objects where each object represents one data point
- Use simple, descriptive field names (e.g., 'date', 'value', 'category', 'count')
- Ensure numeric values are actual numbers, not strings
- For time data, use ISO date strings or simple date formats

User's original query: {user_query}
Raw data (in CSV format):
{raw_data}

Analyze this data and generate 1-2 compelling chart insights. Focus on the most important patterns that answer the user's query.

For each insight:
1. Choose the best chart type for the data pattern
2. Transform data into Recharts format (array of objects with simple field names)
3. Provide clear axis field names
4. Write a compelling insight description

Return 1 insight if the data is simple/focused, or 2 insights if there are multiple interesting patterns to explore.
            """,
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
    Analyzes raw data and generates 1-2 chart insights with Recharts-compatible data.

    This simplified tool combines insight planning and chart creation into a single step.
    It analyzes the raw data and generates compelling visualizations that answer the user's query.

    Args:
        query: The user's original query to provide context for insights.
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
                        status="error"
                    )
                ]
            }
        )

    raw_data = state["raw_data"]
    logger.debug(f"Processing data with {len(raw_data)} rows")

    # Convert DataFrame to CSV string for the prompt
    if isinstance(raw_data, pd.DataFrame):
        data_csv = raw_data.to_csv(index=False)
        logger.debug(f"Data columns: {list(raw_data.columns)}")
    else:
        data_csv = str(raw_data)

    # Generate insights using the LLM
    try:
        chain = INSIGHT_GENERATION_PROMPT | SONNET.with_structured_output(
            InsightResponse
        )
        response = chain.invoke({"user_query": query, "raw_data": data_csv})

        insights = response.insights
        logger.debug(f"Generated {len(insights)} insights")

        # Format the response message
        message_parts = []
        charts_data = []

        for i, insight in enumerate(insights, 1):
            logger.debug(
                f"Insight {i}: {insight.title} ({insight.chart_type})"
            )

            message_parts.append(f"**Insight {i}: {insight.title}**")
            message_parts.append(f"Chart Type: {insight.chart_type}")
            message_parts.append(f"Key Finding: {insight.insight}")
            message_parts.append(f"Data Points: {len(insight.data)}")
            message_parts.append("")

            # Store chart data for frontend
            charts_data.append(
                {
                    "id": f"chart_{i}",
                    "title": insight.title,
                    "type": insight.chart_type,
                    "insight": insight.insight,
                    "data": insight.data,
                    "xAxis": insight.x_axis,
                    "yAxis": insight.y_axis,
                    "colorField": insight.color_field,
                }
            )

        tool_message = "\n".join(message_parts)

        # Update state with generated insights
        updated_state = {
            "insights": response.model_dump()["insights"],
            "charts_data": charts_data,
            "insight_count": len(insights),
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
                        status="error"
                    )
                ]
            }
        )


if __name__ == "__main__":
    # Example usage for testing

    # Test with time series data
    mock_state_1 = {
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

    result_1 = generate_insights.func(
        query="What are the trends in deforestation alerts over time?",
        state=mock_state_1,
        tool_call_id="test-id-1",
    )

    print("=== Time Series Test ===")
    print(result_1.update["messages"][0].content)

    # Test with categorical data
    mock_state_2 = {
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

    result_2 = generate_insights.func(
        query="Which countries have the highest forest loss?",
        state=mock_state_2,
        tool_call_id="test-id-2",
    )

    print("\n=== Categorical Test ===")
    print(result_2.update["messages"][0].content)
