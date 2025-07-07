from typing import Annotated, Dict, List, Optional, Any

import pandas as pd
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator
import json

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# LLM
sonnet = ChatAnthropic(model="claude-3-7-sonnet-latest", temperature=0)


class ChartData(BaseModel):
    """
    Represents a complete chart with data and metadata.
    """
    
    chart_id: str = Field(
        description="Unique identifier for this chart"
    )
    chart_type: str = Field(
        description="Chart type: 'line', 'bar', 'pie', 'stacked-bar', 'divergent-bar', or 'table'"
    )
    title: str = Field(
        description="Chart title"
    )
    insight: str = Field(
        description="Key insight or finding that this chart reveals"
    )
    data: Dict[str, Any] = Field(
        description="Chart.js compatible data structure"
    )
    options: Dict[str, Any] = Field(
        description="Chart.js options for styling and configuration"
    )
    focus: str = Field(
        description="The specific aspect of data this chart focuses on"
    )
    
    @field_validator('data', mode='before')
    @classmethod
    def parse_data_json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # If it's not valid JSON, return empty dict
                return {}
        return v
    
    @field_validator('options', mode='before')
    @classmethod
    def parse_options_json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # If it's not valid JSON, return empty dict
                return {}
        return v


CHART_CREATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "user",
            """
You are Zeno, a data visualization expert. Create a Chart.js compatible chart based on the provided data and focus area.

Your task:
1. Transform the raw data into the appropriate Chart.js format for the specified chart type
2. Generate appropriate labels, datasets, and styling
3. Provide a clear title and insight
4. Configure chart options for best readability

Chart Type: {chart_type}
Focus Area: {focus}
User Query: {user_query}

Raw Data (CSV format):
{raw_data_csv}

Chart.js Format Guidelines:

**Line Chart:**
```json
{{
  "data": {{
    "labels": ["Jan", "Feb", "Mar"],
    "datasets": [{{
      "label": "Series Name",
      "data": [10, 20, 30],
      "borderColor": "rgb(75, 192, 192)",
      "backgroundColor": "rgba(75, 192, 192, 0.2)"
    }}]
  }},
  "options": {{
    "responsive": true,
    "scales": {{
      "y": {{"beginAtZero": true}}
    }}
  }}
}}
```

**Bar Chart:**
```json
{{
  "data": {{
    "labels": ["Category A", "Category B"],
    "datasets": [{{
      "label": "Values",
      "data": [10, 20],
      "backgroundColor": ["rgba(255, 99, 132, 0.2)", "rgba(54, 162, 235, 0.2)"]
    }}]
  }},
  "options": {{
    "responsive": true,
    "scales": {{
      "y": {{"beginAtZero": true}}
    }}
  }}
}}
```

**Pie Chart:**
```json
{{
  "data": {{
    "labels": ["Red", "Blue", "Yellow"],
    "datasets": [{{
      "data": [300, 50, 100],
      "backgroundColor": ["#FF6384", "#36A2EB", "#FFCE56"]
    }}]
  }},
  "options": {{
    "responsive": true,
    "plugins": {{
      "legend": {{"position": "top"}}
    }}
  }}
}}
```

**Stacked Bar Chart:**
```json
{{
  "data": {{
    "labels": ["Jan", "Feb"],
    "datasets": [
      {{
        "label": "Series 1",
        "data": [10, 20],
        "backgroundColor": "rgba(255, 99, 132, 0.2)"
      }},
      {{
        "label": "Series 2", 
        "data": [15, 25],
        "backgroundColor": "rgba(54, 162, 235, 0.2)"
      }}
    ]
  }},
  "options": {{
    "responsive": true,
    "scales": {{
      "x": {{"stacked": true}},
      "y": {{"stacked": true}}
    }}
  }}
}}
```

**Table Format:**
```json
{{
  "data": {{
    "headers": ["Column 1", "Column 2"],
    "rows": [
      ["Value 1", "Value 2"],
      ["Value 3", "Value 4"]
    ]
  }},
  "options": {{
    "responsive": true,
    "striped": true,
    "bordered": true
  }}
}}
```

Instructions:
- Use appropriate colors and styling
- Ensure data is properly aggregated/filtered for the focus area
- Make labels clear and readable
- Include proper units in labels where applicable
- Generate a compelling title and insight based on what the data shows
- For time series, ensure proper date formatting
- For categorical data, consider sorting by value when appropriate

Generate a complete chart configuration that tells a clear story about the data.
""",
        )
    ]
)

# Create the chart creation chain
chart_creation_chain = CHART_CREATION_PROMPT | sonnet.with_structured_output(ChartData)


def generate_chart_id(focus: str, chart_type: str) -> str:
    """Generate a unique chart ID based on focus and type."""
    import hashlib
    content = f"{focus}_{chart_type}"
    return f"chart_{hashlib.md5(content.encode()).hexdigest()[:8]}"


@tool("create-chart")
def create_chart(
    insight_focus: str,
    chart_type: Optional[str] = None,
    query: Optional[str] = None,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Creates a specific chart based on a planned insight focus area.
    
    This tool transforms raw data into a Chart.js compatible visualization
    focused on a specific aspect of the data (e.g., temporal trends, 
    category distribution, regional comparison).
    
    Args:
        insight_focus: The specific aspect to focus on (from insight plan).
        chart_type: Optional override for chart type.
        query: Optional user query for additional context.
        state: The current state containing raw_data and optionally insight_plan.
        tool_call_id: Tool call identifier for response tracking.
    """
    logger.info(f"CREATE-CHART-TOOL: {insight_focus}")
    
    raw_data = state.get("raw_data")
    if not raw_data:
        logger.warning("No raw data found to create chart from.")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="No raw data found to create chart from. Please reframe your query.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )
    
    # Get insight plan if available to find matching planned insight
    insight_plan = state.get("insight_plan", {})
    planned_insights = insight_plan.get("insights", [])
    
    # Find matching planned insight or use provided parameters
    matching_insight = None
    for insight in planned_insights:
        if insight["focus"].lower() in insight_focus.lower() or insight_focus.lower() in insight["focus"].lower():
            matching_insight = insight
            break
    
    # Determine chart type and query
    if chart_type is None and matching_insight:
        chart_type = matching_insight["suggested_chart_type"]
    elif chart_type is None:
        chart_type = "bar"  # Default fallback
    
    if query is None:
        query = state.get("original_query", "Analyze the data")
    
    # Convert raw data to DataFrame and CSV
    df = pd.DataFrame(raw_data)
    raw_data_csv = df.to_csv(index=False)
    
    logger.debug(f"Creating {chart_type} chart focused on: {insight_focus}")
    
    try:
        # Generate the chart
        chart_data = chart_creation_chain.invoke(
            {
                "chart_type": chart_type,
                "focus": insight_focus,
                "user_query": query,
                "raw_data_csv": raw_data_csv,
            }
        )
        
        # Set chart ID
        chart_data.chart_id = generate_chart_id(insight_focus, chart_type)
        chart_data.focus = insight_focus
        
        logger.debug(f"Successfully created chart: {chart_data.title}")
        
        # Update state with the new chart
        generated_charts = state.get("generated_charts", [])
        
        # Remove any existing chart with the same focus (for updates)
        generated_charts = [c for c in generated_charts if c.get("focus") != insight_focus]
        
        # Add new chart
        generated_charts.append(chart_data.model_dump())
        
        tool_message = ToolMessage(
            content=f"Successfully created {chart_type} chart: '{chart_data.title}' - {chart_data.insight}",
            tool_call_id=tool_call_id,
        )
        
        return Command(
            update={
                "generated_charts": generated_charts,
                "messages": [tool_message],
            }
        )
        
    except Exception as e:
        logger.error(f"Error creating chart: {e}")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Error creating chart: {str(e)}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )


@tool("list-available-insights")
def list_available_insights(
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Lists all planned insights that haven't been generated yet.
    
    Useful for multi-turn conversations where users want to see what
    other insights are available or request specific ones.
    """
    logger.info("LIST-AVAILABLE-INSIGHTS-TOOL")
    
    insight_plan = state.get("insight_plan", {})
    planned_insights = insight_plan.get("insights", [])
    generated_charts = state.get("generated_charts", [])
    
    if not planned_insights:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="No insight plan found. Please run plan-insights first.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )
    
    # Find which insights haven't been generated yet
    generated_focuses = {chart.get("focus", "") for chart in generated_charts}
    available_insights = [
        insight for insight in planned_insights 
        if insight["focus"] not in generated_focuses
    ]
    
    if not available_insights:
        message = "All planned insights have been generated."
    else:
        insights_list = "\n".join([
            f"{i+1}. {insight['title']} ({insight['suggested_chart_type']}) - {insight['rationale']}"
            for i, insight in enumerate(available_insights)
        ])
        message = f"Available insights to generate:\n{insights_list}"
    
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=message,
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
        ],
        "original_query": "Show me deforestation trends"
    }
    
    result = create_chart(
        insight_focus="temporal trends",
        chart_type="line",
        query="Show me deforestation trends",
        state=mock_state,
        tool_call_id="test_call_id"
    )
    
    print("Chart Creation Result:")
    print(result)
