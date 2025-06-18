from langchain_anthropic import ChatAnthropic

from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver

from src.tools import (
    pick_aoi,
    pick_dataset,
    pull_data,
    generate_insights,
)
from src.graph import AgentState

prompt = """You are a geospatial agent that has access to tools to help answer user queries. Plan your actions carefully and use the tools to answer the user's question.

Tools:
- pick-aoi: Pick the best area of interest (AOI) based on a place name and user's question. Optionally, it can also filter the results by a subregion.
- pick-dataset: Find the most relevant datasets to help answer the user's question.
- pull-data: Pulls data for the selected AOI and dataset.
- generate-insights: Analyzes raw data in the context of the user's query to generate a structured insight.

End with a 1-line summary of the insights you generated.
"""

sonnet = ChatAnthropic(model="claude-3-7-sonnet-latest", temperature=0)
tools = [
    pick_aoi,
    pick_dataset,
    pull_data,
    generate_insights,
]

checkpointer = InMemorySaver()

zeno = create_react_agent(
    model=sonnet,
    tools=tools,
    state_schema=AgentState,
    prompt=prompt,
    checkpointer=checkpointer,
)