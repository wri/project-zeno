from typing import Annotated, Dict, List

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

logger = get_logger(__name__)

# LLM
sonnet = ChatAnthropic(model="claude-3-7-sonnet-latest", temperature=0)


class PlannedInsight(BaseModel):
    """
    Represents a planned insight that can be turned into a chart.
    """
    
    focus: str = Field(
        description="The specific aspect of data this insight focuses on (e.g., 'temporal trends', 'regional distribution', 'category breakdown')"
    )
    suggested_chart_type: str = Field(
        description="Recommended chart type: 'line', 'bar', 'pie', 'stacked-bar', 'divergent-bar', or 'table'"
    )
    priority: int = Field(
        description="Priority ranking (1=highest priority, should be generated first)"
    )
    rationale: str = Field(
        description="Brief explanation of why this insight is valuable for the user's query"
    )
    title: str = Field(
        description="Suggested title for this chart/insight"
    )


class InsightPlan(BaseModel):
    """
    Contains multiple planned insights for a dataset.
    """
    
    insights: List[PlannedInsight] = Field(
        description="List of planned insights, ordered by priority"
    )
    data_summary: str = Field(
        description="Brief summary of the dataset characteristics"
    )


INSIGHT_PLANNING_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "user",
            """
You are Zeno, a helpful AI assistant that analyzes environmental data and plans insightful visualizations.

Your task is to analyze the provided dataset and create a plan for 2-4 complementary insights that would best answer the user's query.

Consider these chart types and their best use cases:
- **line**: Time series, trends over time, continuous data progression
- **bar**: Comparing categories, rankings, discrete comparisons
- **pie**: Composition, parts of a whole, percentage breakdowns (use sparingly, only when percentages matter)
- **stacked-bar**: Multiple categories over time/groups, showing both total and composition
- **divergent-bar**: Comparing positive/negative values, before/after comparisons
- **table**: Detailed data, precise values, when visualization isn't the best format

Guidelines:
1. Prioritize insights that directly answer the user's question
2. Ensure insights are complementary, not redundant
3. Consider the data characteristics (temporal, categorical, numerical, geographical)
4. Limit to 2-4 insights maximum - quality over quantity
5. Avoid pie charts unless composition/percentages are specifically relevant
6. Consider what story the data tells and plan insights that build that narrative

User's original query: {user_query}
AOI (Area of Interest): {aoi}
Dataset: {dataset}

Dataset preview (first few rows):
{data_preview}

Dataset summary:
- Shape: {data_shape}
- Columns: {columns}
- Data types: {dtypes}

Plan insights that would be most valuable for answering the user's query about this data.
""",
        )
    ]
)

# Create the insight planning chain
insight_planning_chain = INSIGHT_PLANNING_PROMPT | sonnet.with_structured_output(
    InsightPlan
)


@tool("plan-insights")
def plan_insights(
    query: str,
    aoi: str,
    dataset: str,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Analyzes raw data and creates a plan for the most valuable insights/charts to generate.
    
    This tool examines the dataset characteristics and user query to determine what
    types of insights would be most valuable, suggesting appropriate chart types
    and prioritizing them by importance.
    
    Args:
        query: The user's original query to provide context for insight planning.
        aoi: Area of interest for context.
        dataset: Dataset name for context.
    """
    logger.info("PLAN-INSIGHTS-TOOL")
    
    raw_data = state.get("raw_data")
    if not raw_data:
        logger.warning("No raw data found to plan insights from.")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="No raw data found to plan insights from. Please reframe your query.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )
    
    # Convert raw data to DataFrame for analysis
    df = pd.DataFrame(raw_data)
    logger.debug(f"Analyzing DataFrame with shape: {df.shape}")
    
    # Prepare data summary for the LLM
    data_preview = df.head(10).to_csv(index=False)
    data_shape = f"{df.shape[0]} rows, {df.shape[1]} columns"
    columns = list(df.columns)
    dtypes = df.dtypes.to_dict()
    
    # Generate the insight plan
    logger.debug("Invoking insight planning chain...")
    try:
        insight_plan = insight_planning_chain.invoke(
            {
                "user_query": query,
                "aoi": aoi,
                "dataset": dataset,
                "data_preview": data_preview,
                "data_shape": data_shape,
                "columns": columns,
                "dtypes": {k: str(v) for k, v in dtypes.items()},
            }
        )
        logger.debug(f"Successfully planned {len(insight_plan.insights)} insights")
        
        # Create summary message
        insights_summary = "\n".join([
            f"{i+1}. {insight.title} ({insight.suggested_chart_type}) - {insight.rationale}"
            for i, insight in enumerate(insight_plan.insights)
        ])
        
        tool_message = ToolMessage(
            content=f"Successfully planned {len(insight_plan.insights)} insights:\n{insights_summary}",
            tool_call_id=tool_call_id,
        )
        
        return Command(
            update={
                "insight_plan": insight_plan.model_dump(),
                "messages": [tool_message],
            }
        )
        
    except Exception as e:
        logger.error(f"Error planning insights: {e}")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Error planning insights: {str(e)}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )


if __name__ == "__main__":
    # Example usage for testing
    mock_state = {
        "raw_data": [
            {"year": 2020, "country": "Brazil", "deforestation": 11088, "region": "Amazon"},
            {"year": 2021, "country": "Brazil", "deforestation": 13038, "region": "Amazon"},
            {"year": 2022, "country": "Brazil", "deforestation": 11568, "region": "Amazon"},
            {"year": 2020, "country": "Indonesia", "deforestation": 2720, "region": "Southeast Asia"},
            {"year": 2021, "country": "Indonesia", "deforestation": 2934, "region": "Southeast Asia"},
            {"year": 2022, "country": "Indonesia", "deforestation": 2080, "region": "Southeast Asia"},
        ]
    }
    
    result = plan_insights(
        query="Show me deforestation trends in tropical countries",
        aoi="Global",
        dataset="Forest Loss Data",
        state=mock_state,
        tool_call_id="test_call_id"
    )
    
    print("Insight Plan Result:")
    print(result)
