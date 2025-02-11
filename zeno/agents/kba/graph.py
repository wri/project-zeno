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
from langgraph.prebuilt import ToolNode, tools_condition

from zeno.agents.kba.agent import kba_agent, tools, tools_with_hil_names, tools_with_hil
from zeno.agents.kba.prompts import KBA_PROMPT
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


def kba_node(state: KbaState):
    print("kba node")
    kba_prompt = SystemMessage(content=KBA_PROMPT)
    result = kba_agent.invoke([kba_prompt] + state["messages"])

    return {"messages": [result], "user_persona": state["user_persona"]}


def route_node(state: KbaState):
    next_node = tools_condition(state)
    if next_node == END:
        return END
    msg = state["messages"][-1]
    tc = msg.tool_calls[0]
    if tc["name"] in tools_with_hil_names:
        return "tools_with_hil"
    else:
        return "tools"


wf = StateGraph(KbaState)

wf.add_node("kba_node", kba_node)
wf.add_node("tools", create_tool_node_with_fallback(tools))
wf.add_node("tools_with_hil", create_tool_node_with_fallback(tools_with_hil))

wf.add_edge(START, "kba_node")
wf.add_conditional_edges(
    "kba_node",
    route_node,
    {"tools": "tools", "tools_with_hil": "tools_with_hil", END: END},
)
wf.add_edge("tools", "kba_node")
wf.add_edge("tools_with_hil", "kba_node")

memory = MemorySaver()
graph = wf.compile(checkpointer=memory, interrupt_after=["tools_with_hil"])
graph.name = "kba"
