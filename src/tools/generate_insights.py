import json
from typing import Annotated, Dict, List
import pandas as pd
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field
from langchain_core.messages import ToolMessage

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# LLM
sonnet = ChatAnthropic(model="claude-3-7-sonnet-latest", temperature=0)

class Insight(BaseModel):
    """
    Represents an insight generated from the data.
    """
    title: str = Field(description="A concise and descriptive title for the insight.")
    short_description: str = Field(description="A brief summary of the key findings.")
    data_table: str = Field(description="The data supporting the insight, formatted as a markdown table.")

INSIGHT_GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "user",
            """
You are Zeno, a helpful AI assistant helping users analyze environmental data.
Your task is to generate a compelling insight from the provided raw data, keeping the original user query in mind.

The insight should have three parts:
1.  A `title`: A short, catchy title that summarizes the main finding.
2.  A `short_description`: A one or two-sentence summary that explains the insight.
3.  A `data_table`: The raw data formatted as a markdown table to support the finding.

User's original query: {user_query}
Raw data (in CSV format):
{raw_data}

Generate the insight based on the data and the user's query.
""",
        )
    ]
)

insight_generation_chain = INSIGHT_GENERATION_PROMPT | sonnet.with_structured_output(Insight)

@tool("generate-insights")
def generate_insights(
    query: str,
    aoi: str,
    dataset: str,
    state: Annotated[Dict, InjectedState] | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
) -> Command:
    """
    Analyzes raw data in the context of the user's query to generate a structured insight.

    This tool takes the raw data pulled from a data source and uses an AI model
    to generate a title, a short description, and a data table that represent
    a key insight from the data.

    Args:
        query: The user's original query to provide context for the insight.
        state: The current state of the agent, which must contain 'raw_data'.
    """
    logger.info(f"GENERATE-INSIGHTS-TOOL")

    raw_data = state.get("raw_data")
    if not raw_data: # raw_data is None or empty
        logger.warning("No raw data found to generate insights from.")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="No raw data found to generate insights from.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # Convert raw data to a pandas DataFrame for easier handling and table formatting
    df = pd.DataFrame(raw_data)
    logger.debug(f"Converted raw data to DataFrame with shape: {df.shape}")
    
    # Generate the insight
    logger.debug("Invoking insight generation chain...")
    insight = insight_generation_chain.invoke({
        "user_query": query,
        "raw_data": df.to_csv(index=False),
    })
    logger.debug(f"Successfully generated insight: '{insight.title}'")
    
    # Convert dataframe to markdown for the insight object

    tool_message = ToolMessage(
        content=f"Successfully generated an insight: '{insight.title}'. Raw data: {df.to_csv(index=False)}",
        tool_call_id=tool_call_id,
    )

    return Command(
        update={
            "insights": insight.model_dump(),
            "messages": [tool_message],
        },
    )

if __name__ == "__main__":
    # Example usage for testing
    mock_state = {
        "messages": [{"role": "user", "content": "How much tree cover was lost in Indonesia in 2020?"}],
        "raw_data": [
            {'adm1': 1, 'adm2': 1, 'umd_tree_cover_loss__year': 2020, 'umd_tree_cover_density_2000__threshold': 30, 'umd_tree_cover_loss__ha': 1000.0},
            {'adm1': 1, 'adm2': 2, 'umd_tree_cover_loss__year': 2020, 'umd_tree_cover_density_2000__threshold': 30, 'umd_tree_cover_loss__ha': 2500.5},
            {'adm1': 2, 'adm2': 3, 'umd_tree_cover_loss__year': 2020, 'umd_tree_cover_density_2000__threshold': 30, 'umd_tree_cover_loss__ha': 500.75},
        ]
    }

    # To test the tool's logic directly, we call its underlying function (`.func`).
    # The `@tool` decorator wraps the function, and `.func` gives us access to the original.
    # This bypasses the LangChain machinery that gets confused by the `InjectedState`
    # when the tool is not run within a LangGraph agent.
    user_query = mock_state["messages"][0]["content"]
    command = generate_insights.func(query=user_query, aoi="Indonesia", dataset="Tree cover loss", state=mock_state, tool_call_id="test-id")
    
    logger.info("--- Generated Command ---")
    logger.info(command)
