import os
import contextlib
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres import PostgresSaver

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

DATABASE_URL = os.environ["DATABASE_URL"].replace(
    "postgresql+psycopg://", "postgresql://"
)


@contextlib.contextmanager
def persistent_checkpointer():
    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        # Note: no need to run `checkpointer.setup()` here, since I've
        # converted the checkpointer setup into Alembic migrations so
        # that Alembic can manage the database schema. Note that if we
        # update the postgres checkpointer library it may require a new
        # migration to be created - I manually ran `checkpointer.setup()`
        # on a local database and then ran
        # `alembic revision --autogenerate -m "Add langgraph persistence tables"`
        # to create the migration script (note that the desired migration
        # scripts were created in the opposite methods (upgrade vs downgrade)
        # than the ones expected, since, technically alembic would need to
        # drop the tables in order to get the state to match the local
        # codebase. I just copy/pasted the code from the `upgrade` method
        # to the `downgrade` method).

        # checkpointer.setup()

        yield checkpointer


# Open the context manager at the module level and keep it open
checkpointer_cm = persistent_checkpointer()
checkpointer = checkpointer_cm.__enter__()
zeno = create_react_agent(
    model=model,
    tools=tools,
    state_schema=AgentState,
    prompt=prompt,
    checkpointer=checkpointer,
)
