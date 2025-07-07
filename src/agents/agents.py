import contextlib
import os

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.prebuilt import create_react_agent

from src.graph import AgentState
from src.tools import (
    create_chart,
    list_available_insights,
    pick_aoi,
    pick_dataset,
    plan_insights,
    pull_data,
)

prompt = """You are a geospatial agent that has access to tools to help answer user queries. Plan your actions carefully and use the tools to answer the user's question.

Tools:
- pick-aoi: Pick the best area of interest (AOI) based on a place name and user's question. Optionally, it can also filter the results by a subregion.
- pick-dataset: Find the most relevant datasets to help answer the user's question.
- pull-data: Pulls data for the selected AOI and dataset.
- plan-insights: Analyzes raw data and creates a plan for the most valuable insights/charts to generate.
- create-chart: Creates a specific chart based on a planned insight focus area.
- list-available-insights: Lists all planned insights that haven't been generated yet.

Workflow:
1. Use pick-aoi, pick-dataset, and pull-data to get the data
2. Use plan-insights to analyze the data and plan 2-4 valuable insights
3. Use create-chart to generate the top 2-3 most important charts from the plan
4. End with a summary of the key insights revealed by the charts

For multi-turn conversations:
- Users can request specific charts: "show me the pie chart" or "make this a bar chart"
- Use list-available-insights to show what other charts are available
- Use create-chart with different focus areas or chart types as requested

Note: If the dataset is not available, politely inform the user & STOP - don't do any more steps further.
"""

sonnet = ChatAnthropic(model="claude-3-7-sonnet-latest", temperature=0)
tools = [
    pick_aoi,
    pick_dataset,
    pull_data,
    plan_insights,
    create_chart,
    list_available_insights,
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
    model=sonnet,
    tools=tools,
    state_schema=AgentState,
    prompt=prompt,
    checkpointer=checkpointer,
)
