from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from zeno.agents.distalert.utils.nodes import assistant, tool_node
from zeno.agents.maingraph.utils.state import GraphState

wf = StateGraph(GraphState)

wf.add_node("assistant", assistant)
wf.add_node("tools", tool_node)

wf.add_edge(START, "assistant")
wf.add_conditional_edges("assistant", tools_condition)
wf.add_edge("tools", "assistant")
wf.add_edge("assistant", END)

graph = wf.compile()
