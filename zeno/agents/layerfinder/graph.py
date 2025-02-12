import json

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from zeno.agents.layerfinder.agent import layerfinder_agent, haiku
from zeno.agents.layerfinder.prompts import (
    LAYER_FINDER_RAG_PROMPT,
    LAYER_DETAILS_PROMPT,
)
from zeno.agents.layerfinder.state import LayerFinderState
from zeno.agents.layerfinder.tool_layer_retrieve import retriever
from zeno.agents.layerfinder.utils import make_context


def retrieve_node(state: LayerFinderState):
    print("---RETRIEVE---")
    question = state["question"]
    documents = retriever.invoke(question)
    return {"documents": documents}


def validation_node(state: LayerFinderState):
    print("---VALIDATE---")
    question = state["question"]
    documents = state["documents"]

    docs_txt = make_context(documents)
    rag_prompt_fmt = LAYER_FINDER_RAG_PROMPT.format(context=docs_txt, question=question)

    data = layerfinder_agent.invoke([HumanMessage(content=rag_prompt_fmt)])

    data.datasets = [data for data in data.datasets if data.score]

    return {"validated_documents": data}


def route_node(state: LayerFinderState):
    print("---ROUTE---", state)
    if state.get("ds_id"):
        return "detail"
    else:
        return "retrieve"


def explain_details_node(state: LayerFinderState):
    print("---EXPLAIN DETAILS---")
    ds_id = state["ds_id"]
    dataset = [ds for ds in state["documents"] if ds_id == ds.metadata["dataset"]]
    if not dataset:
        return {"messages": [AIMessage("No dataset found")]}
    else:
        dataset = dataset[0]
    prompt = LAYER_DETAILS_PROMPT.format(
        context=dataset.page_content, question=state["question"]
    )
    response = haiku.invoke(prompt)
    return {"messages": [response]}


wf = StateGraph(LayerFinderState)

wf.add_node("retrieve", retrieve_node)
wf.add_node("validate", validation_node)
wf.add_node("detail", explain_details_node)

wf.add_conditional_edges(START, route_node)
wf.add_edge("retrieve", "validate")
wf.add_edge("validate", END)
wf.add_edge("detail", END)

memory = MemorySaver()
graph = wf.compile(checkpointer=memory)
graph.name = "layerfinder"
