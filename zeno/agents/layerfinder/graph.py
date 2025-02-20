from multiprocessing import Pool
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from zeno.agents.docfinder.graph import graph as docfinder
from zeno.agents.layerfinder.agent import haiku, layerfinder_agent
from zeno.agents.layerfinder.prompts import (
    LAYER_CAUTIONS_PROMPT,
    LAYER_DETAILS_PROMPT,
    LAYER_FINDER_PROMPT,
    ROUTING_PROMPT,
)
from zeno.agents.layerfinder.state import LayerFinderState
from zeno.agents.layerfinder.tool_layer_retrieve import db


def call_agent(prompt):
    return layerfinder_agent.invoke([HumanMessage(content=prompt)])


def retrieve_node(state: LayerFinderState):
    print("---RETRIEVE---")
    question = state["question"]
    search_result = db.similarity_search_with_relevance_scores(
        question, k=10, score_threshold=0.3
    )

    documents = []
    for doc, score in search_result:
        doc.metadata.update(relevance=score)
        documents.append(doc)

    prompts = []
    for doc in documents:
        prompt = LAYER_FINDER_PROMPT.format(
            context=f"Dataset: {doc.metadata['zeno_id']}\n{doc.page_content}",
            question=question,
        )
        prompts.append(prompt)
    if prompts:
        with Pool(len(prompts)) as p:
            datasets = p.map(call_agent, prompts)
    else:
        datasets = []

    for dataset in datasets:
        doc = [doc for doc in documents if doc.metadata["zeno_id"] == dataset.dataset][
            0
        ]
        dataset.metadata = doc.metadata
        dataset.uri = doc.metadata["gfw_metadata_url"]
        dataset.tilelayer = doc.metadata["gfw_tile_url"]

    return {"datasets": datasets}


def cautions_node(state: LayerFinderState):
    print("---CAUTIONS---")
    question = state["question"]
    cautions = "\n".join([ds.metadata["cautions"] for ds in state["datasets"]])
    prompt = LAYER_CAUTIONS_PROMPT.format(
        cautions=cautions,
        question=question,
    )
    haiku_response = haiku.invoke(prompt)
    return {"messages": [haiku_response]}


def route_node(state: LayerFinderState):
    print("---ROUTE---")

    class RouteResponse(BaseModel):
        route: Literal["retrieve", "docfinder"]

    choice = haiku.with_structured_output(RouteResponse).invoke(
        ROUTING_PROMPT.format(question=state["question"])
    )
    print(f"---Route Chosen: {choice.route}---")
    return choice.route


def docfinder_node(state: LayerFinderState):
    return docfinder.invoke([HumanMessage(content=state["question"])])


def explain_details_node(state: LayerFinderState):
    print("---EXPLAIN DETAILS---")
    ds_id = state["ds_id"]
    dataset = [ds for ds in state["datasets"] if ds_id == ds.metadata["dataset"]]
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
wf.add_node("detail", explain_details_node)
wf.add_node("cautions", cautions_node)
wf.add_node("docfinder", docfinder)

wf.add_conditional_edges(START, route_node)
wf.add_edge("retrieve", "cautions")
wf.add_edge("cautions", END)
wf.add_edge("detail", END)
wf.add_edge("docfinder", END)

memory = MemorySaver()
graph = wf.compile(checkpointer=memory)
graph.name = "layerfinder"
