import os
import contextlib
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from zeno.agents.gfw_data_api.agent import (
    gfw_data_api_agent,
    tools,
    tools_with_hil,
    tools_with_hil_names,
)
from zeno.agents.gfw_data_api.prompts import GFW_DATA_API_PROMPT
from zeno.agents.gfw_data_api.state import GFWDataAPIState


def handle_tool_error(state: GFWDataAPIState) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


def create_tool_node_with_fallback(tools: list) -> dict:
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


def gfw_data_api_node(state: GFWDataAPIState, config: RunnableConfig) -> dict:
    gfw_data_api_prompt = SystemMessage(content=GFW_DATA_API_PROMPT)
    result = gfw_data_api_agent.invoke(
        [gfw_data_api_prompt] + state["messages"], config
    )

    return {"messages": result}


def route_tools(state: GFWDataAPIState) -> str:
    next_node = tools_condition(state)
    if next_node == END:
        return END
    msg = state["messages"][-1]
    tc = msg.tool_calls[0]
    if tc["name"] in tools_with_hil_names:
        return "tools_with_hil"
    else:
        return "tools"


wf = StateGraph(GFWDataAPIState)

wf.add_node("gfw_data_api", gfw_data_api_node)
wf.add_node("tools", create_tool_node_with_fallback(tools))
wf.add_node("tools_with_hil", create_tool_node_with_fallback(tools_with_hil))

wf.add_edge(START, "gfw_data_api")
wf.add_conditional_edges("gfw_data_api", route_tools, ["tools", "tools_with_hil", END])
wf.add_edge("tools", "gfw_data_api")
wf.add_edge("tools_with_hil", "gfw_data_api")


# Langgraph's checkpointer doesn't use SQLAlchemy/alembic, so we need to remove `pyscopg` from the DATABASE_URL
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


graph = wf.compile(checkpointer=checkpointer, interrupt_after=["tools_with_hil"])
graph.name = "GFWDataAPI"
