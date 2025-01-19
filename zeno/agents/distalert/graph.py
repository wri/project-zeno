from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from zeno.agents.distalert.agent import (
    dist_alert_agent,
    tools,
    tools_with_hil,
    tools_with_hil_names,
)
from zeno.agents.distalert.prompts import DIST_ALERTS_PROMPT
from zeno.agents.distalert.state import DistAlertState


def handle_tool_error(state: DistAlertState) -> dict:
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


def dist_alert_node(state: DistAlertState, config: RunnableConfig) -> dict:
    dist_alert_prompt = SystemMessage(content=DIST_ALERTS_PROMPT)
    result = dist_alert_agent.invoke(
        [dist_alert_prompt] + state["messages"], config
    )

    return {"messages": result}


def route_tools(state: DistAlertState) -> str:
    next_node = tools_condition(state)
    if next_node == END:
        return END
    msg = state["messages"][-1]
    tc = msg.tool_calls[0]
    if tc["name"] in tools_with_hil_names:
        return "tools_with_hil"
    else:
        return "tools"


wf = StateGraph(DistAlertState)

wf.add_node("dist_alert", dist_alert_node)
wf.add_node("tools", create_tool_node_with_fallback(tools))
wf.add_node("tools_with_hil", create_tool_node_with_fallback(tools_with_hil))

wf.add_edge(START, "dist_alert")
wf.add_conditional_edges(
    "dist_alert", route_tools, ["tools", "tools_with_hil", END]
)
wf.add_edge("tools", "dist_alert")
wf.add_edge("tools_with_hil", "dist_alert")

memory = MemorySaver()
dist_alert = wf.compile(
    checkpointer=memory, interrupt_after=["tools_with_hil"]
)
dist_alert.name = "DistAlert"
