from langgraph.graph import END, StateGraph
from agents.layerfinder.utils.state import GraphState
from agents.docfinder.agent import graph as docfinder
from agents.layerfinder.agent import graph as layerfinder
from agents.maingraph.utils.nodes import maingraph
from agents.firealert.agent import graph as firealert

# Define a new graph
workflow = StateGraph(GraphState)

# Define the nodes we will cycle between
workflow.add_node("docfinder", docfinder)
workflow.add_node("layerfinder", layerfinder)
workflow.add_node("firealert", firealert)

workflow.set_conditional_entry_point(
    maingraph,
    {
        "layerfinder": "layerfinder",
        "docfinder": "docfinder",
        "firealert": "firealert",
    },
)
workflow.add_edge("docfinder", END)
workflow.add_edge("layerfinder", END)
workflow.add_edge("firealert", END)

graph = workflow.compile()
