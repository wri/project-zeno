import contextlib
import os

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

from src.graph import AgentState
from src.tools import (
    pick_aoi,
    pick_dataset,
    pull_data,
    generate_insights,
)

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

DATABASE_URL = os.environ["DATABASE_URL"].replace(
    "postgresql+psycopg2://", "postgresql://"
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

# memory = InMemorySaver()

zeno = create_react_agent(
    model=sonnet,
    tools=tools,
    state_schema=AgentState,
    prompt=prompt,
    checkpointer=checkpointer,
)
