from langchain_anthropic import ChatAnthropic

from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver

from src.tools import (
    context_layer_tool,
    dist_alerts_tool,
    kba_data_tool,
    kba_insights_tool,
    kba_timeseries_tool,
    location_tool,
    stac_tool,
    gfw_query_tool,
    dataset_finder_tool,
)
from src.graph import AgentState

prompt = """You are a geospatial agent that has access to tools to help answer user queries.

Tools:
- location-tool: Find location of a place.
- relative-location-tool: Returns a list of GADM Items for a requested GADM Level.
- dist-alerts-tool: Find vegetation disturbance alerts in an area.
- kba-data-tool: Find data on KBA, using either an AOI derived from the location-tool or specific KBA names directly from the user.
- kba-insights-tool: Generates insights based on the data and user query.
- kba-timeseries-tool: Provides trends on specific topics only i.e carbon emissions, tree cover loss, ecosystem productivity & cultivation/agriculture practices.
- gfw-query-tool: Returns a SQL query to retrieve data from the GFW data API based on user input.
- dataset-finder-tool: Finds the most relevant datasets for the user's question. Use this tools when the user is asking for dataset recommentation.

Notes: 
- For tasks like analysing key biodiversity areas or finding disturbance alerts, use the location tool first to pick the AOI
- For queries that are in search of datasets or data layers, use the dataset-finder-tool to find the most relevant datasets.
- For queries related to Global Forest Watch (GFW) data API, use the relative-location-tool to find gadm ids first & then use it to query GFW data api based on user input.
"""

model = ChatAnthropic(model="claude-3-7-sonnet-latest", temperature=0)
tools = [
    location_tool,
    dist_alerts_tool,
    kba_data_tool,
    kba_insights_tool,
    kba_timeseries_tool,
    stac_tool,
    gfw_query_tool,
    dataset_finder_tool,
]

checkpointer = InMemorySaver()

zeno = create_react_agent(
    model=model,
    tools=tools,
    state_schema=AgentState,
    state_modifier=prompt,
    checkpointer=checkpointer,
)
