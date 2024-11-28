from agents.layerfinder.utils.nodes import generate, retrieve
from agents.layerfinder.utils.state import GraphState
from langgraph.graph import END, START, StateGraph

wf = StateGraph(GraphState)

wf.add_node("retrieve", retrieve)
wf.add_node("generate", generate)

wf.add_edge(START, "retrieve")
wf.add_edge("retrieve", "generate")
wf.add_edge("generate", END)

graph = wf.compile()
