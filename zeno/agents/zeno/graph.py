from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from zeno.agents.zeno.agent import (
    tools,
    tools_with_hil,
    tools_with_hil_names,
    zeno_agent,
)
from zeno.agents.zeno.prompts import ZENO_PROMPT
from zeno.agents.zeno.state import ZenoState


def handle_tool_error(state: ZenoState) -> dict:
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


def zeno_node(state: ZenoState, config: RunnableConfig) -> dict:
    zeno_prompt = SystemMessage(content=ZENO_PROMPT)
    result = zeno_agent.invoke([zeno_prompt] + state["messages"], config)

    return {"messages": result}


def route_tools(state: ZenoState) -> str:
    next_node = tools_condition(state)
    if next_node == END:
        return END
    msg = state["messages"][-1]
    tc = msg.tool_calls[0]
    if tc["name"] in tools_with_hil_names:
        return "tools_with_hil"
    else:
        return "tools"


wf = StateGraph(ZenoState)

wf.add_node("zeno", zeno_node)
wf.add_node("tools", create_tool_node_with_fallback(tools))
wf.add_node("tools_with_hil", create_tool_node_with_fallback(tools_with_hil))

wf.add_edge(START, "zeno")
wf.add_conditional_edges("zeno", route_tools, ["tools", "tools_with_hil", END])
wf.add_edge("tools", "zeno")
wf.add_edge("tools_with_hil", "zeno")

memory = MemorySaver()
zeno = wf.compile(checkpointer=memory, interrupt_after=["tools_with_hil"])
# zeno = wf.compile(checkpointer=memory)
zeno.name = "Zeno"
