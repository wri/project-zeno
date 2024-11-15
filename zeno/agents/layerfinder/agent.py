from langgraph.graph import StateGraph
from zeno.agents.layerfinder.utils.nodes import retrieve, generate, assistant, tool_node, router
from langgraph.graph import END
from langgraph.prebuilt import tools_condition
from zeno.agents.layerfinder.utils.state import GraphState

wf = StateGraph(GraphState)

wf.add_node("retrieve", retrieve)
wf.add_node("generate", generate)
wf.add_node("assistant", assistant)
wf.add_node("tools", tool_node)

wf.set_conditional_entry_point(
    router,
    {
        "retrieve": "retrieve",
        "assistant": "assistant"
    }
)
wf.add_edge("retrieve", "generate")
wf.add_edge("generate", END)
wf.add_conditional_edges(
    "assistant",
    tools_condition
)
wf.add_edge("tools", "assistant")
wf.add_edge("assistant", END)

graph = wf.compile()
