import pandas as pd
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    ToolMessage,
    AIMessage,
)
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from zeno.agents.kba.agent import kba_info_agent, kba_response_agent, tools
from zeno.agents.kba.prompts import KBA_INFO_PROMPT
from zeno.agents.kba.state import KbaState

column_description = pd.read_csv("data/kba/kba_column_descriptions.csv").to_csv(
    index=False
)


def handle_tool_error(state: KbaState) -> dict:
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


def kba_info_node(state: KbaState):
    system_prompt = KBA_INFO_PROMPT.format(
        user_persona=state["user_persona"],
        dataset_description=column_description,
    )
    system_messsage = SystemMessage(content=system_prompt)
    response = kba_info_agent.invoke([system_messsage] + state["messages"])

    return {"messages": [response]}


def kba_response_node(state: KbaState):
    response = kba_response_agent.invoke(
        [HumanMessage(content=state["messages"][-2].content)]
        + [AIMessage(content=state["messages"][-1].content)]
    )
    return {"report": response}


def route_node(state: KbaState):
    last_message = state["messages"][-1]
    if not last_message.tool_calls:
        return "respond"
    else:
        return "continue"


wf = StateGraph(KbaState)

wf.add_node("kba_info_node", kba_info_node)
wf.add_node("kba_response_node", kba_response_node)
wf.add_node("tools", create_tool_node_with_fallback(tools))

wf.add_edge(START, "kba_info_node")
wf.add_conditional_edges(
    "kba_info_node",
    route_node,
    {"continue": "tools", "respond": "kba_response_node"},
)
wf.add_edge("tools", "kba_info_node")
wf.add_edge("kba_response_node", END)

memory = MemorySaver()
graph = wf.compile(checkpointer=memory)
graph.name = "kba"
