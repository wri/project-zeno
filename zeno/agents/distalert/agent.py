from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from zeno.agents.distalert.utils.nodes import assistant, tool_node, human_review_location
from zeno.agents.maingraph.utils.state import GraphState

wf = StateGraph(GraphState)

wf.add_node("assistant", assistant)
wf.add_node("tools", tool_node)
wf.add_node("human_review_location", human_review_location)

wf.add_edge(START, "assistant")
wf.add_conditional_edges("assistant", tools_condition)
wf.add_edge("tools", "human_review_location")
wf.add_edge("human_review_location", "assistant")
wf.add_edge("assistant", END)

graph = wf.compile()
