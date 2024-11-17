from langgraph.graph import END, StateGraph
from zeno.agents.layerfinder.utils.state import GraphState
from zeno.agents.docfinder.agent import graph as docfinder
from zeno.agents.layerfinder.agent import graph as layerfinder
from zeno.agents.maingraph.utils.nodes import maingraph, generate

# Define a new graph
workflow = StateGraph(GraphState)

# Define the nodes we will cycle between
workflow.add_node("docfinder", docfinder)
workflow.add_node("layerfinder", layerfinder)
# workflow.add_node("generate", generate)

workflow.set_conditional_entry_point(
    maingraph,
    {
        "layerfinder": "layerfinder",
        "docfinder": "docfinder"
    }
)
workflow.add_edge("docfinder", END)
workflow.add_edge("layerfinder", END)

graph = workflow.compile()
