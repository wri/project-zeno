from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from zeno.agents.distalert.agent import graph as distalert
from zeno.agents.docfinder.agent import graph as docfinder
from zeno.agents.firealert.agent import graph as firealert
from zeno.agents.layerfinder.agent import graph as layerfinder
from zeno.agents.maingraph.utils.nodes import maingraph, slasher
from zeno.agents.maingraph.utils.state import GraphState

# Define a new graph
workflow = StateGraph(GraphState)

# Define the nodes we will cycle between
workflow.add_node("slasher", slasher)
workflow.add_node("docfinder", docfinder)
workflow.add_node("layerfinder", layerfinder)
workflow.add_node("firealert", firealert)
workflow.add_node("distalert", distalert)

workflow.add_edge(START, "slasher")
workflow.add_conditional_edges("slasher", maingraph)
workflow.add_edge("docfinder", END)
workflow.add_edge("layerfinder", END)
workflow.add_edge("firealert", END)
workflow.add_edge("distalert", END)

checkpointer = MemorySaver()

graph = workflow.compile(checkpointer=checkpointer)
