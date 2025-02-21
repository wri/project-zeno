from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from zeno.agents.docfinder.prompts import (
    DOCUMENTS_FOR_DATASETS_PROMPT,
    GENERATE_PROMPT,
)
from zeno.agents.docfinder.state import DocFinderState
from zeno.agents.docfinder.tool_document_retrieve import vectorstore

model = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)


class UseDatasetsResponse(BaseModel):
    use_datasets: Literal["yes", "no"]


def generate_node(state: DocFinderState, config: RunnableConfig):
    """
    Generate answer

    Args:
        state (messages): The current state

    Returns:
         dict: The updated state with re-phrased question
    """
    print("---GENERATE---")

    docs = state["documents"]
    context = "\n".join([doc.page_content for doc in docs])

    questions = ""
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            questions += ", " + msg.content

    prompt = GENERATE_PROMPT.format(questions=questions, context=context)

    response = model.invoke(prompt)
    return {"messages": [response]}


def retrieve_node(state: DocFinderState, config: RunnableConfig) -> dict:
    question = state["question"]
    if "datasets" in state:

        response = model.with_structured_output(UseDatasetsResponse).invoke(
            DOCUMENTS_FOR_DATASETS_PROMPT.format(question=question)
        )
        print("DATASETS INCLUDE", response.use_datasets)
        if response.use_datasets == "yes":
            context = "\n".join(
                [
                    (ds.metadata["title"] + ds.metadata.get("function"))
                    for ds in state["datasets"]
                ]
            )
            question = context
    documents = vectorstore.similarity_search_with_relevance_scores(
        question, k=10, score_threshold=0.3
    )
    return {"documents": [doc[0] for doc in documents]}


wf = StateGraph(DocFinderState)

wf.add_node("retrieve", retrieve_node)
wf.add_node("generate", generate_node)

wf.add_edge(START, "retrieve")
wf.add_edge(
    "retrieve",
    "generate",
)
wf.add_edge("generate", END)

memory = MemorySaver()
graph = wf.compile(checkpointer=memory)
graph.name = "docfinder"
