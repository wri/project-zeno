from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from zeno.agents.docfinder.prompts import (
    DOCUMENT_GRADER_PROMPT,
    GENERATE_PROMPT,
    QUERY_OPTIMIZER_PROMPT,
)
from zeno.agents.docfinder.state import DocFinderState
from zeno.agents.docfinder.tool_document_retrieve import vectorstore

model = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)


def rewrite_node(state: DocFinderState, config: RunnableConfig):
    """
    Transform the query to produce a better question.

    Args:
        state (messages): The current state

    Returns:
        dict: The updated state with re-phrased question
    """

    print("---TRANSFORM QUERY---")
    question = state["question"]

    msg = [
        HumanMessage(
            content=QUERY_OPTIMIZER_PROMPT.format(question=question),
        )
    ]

    # Grader
    response = model.invoke(msg)
    return {"messages": [response]}


def generate_node(state: DocFinderState, config: RunnableConfig):
    """
    Generate answer

    Args:
        state (messages): The current state

    Returns:
         dict: The updated state with re-phrased question
    """
    print("---GENERATE---")
    question = state["question"]

    docs = state["documents"]
    context = "\n".join([doc.page_content for doc in docs])

    prompt = GENERATE_PROMPT.format(question=question, context=context)

    response = model.invoke(prompt)
    return {"messages": [response]}


def grade_documents_edge(
    state: DocFinderState, config: RunnableConfig
) -> Literal["generate", "rewrite"]:
    """
    Determines whether the retrieved documents are relevant to the question.

    Args:
        state (messages): The current state

    Returns:
        str: A decision for whether the documents are relevant or not
    """

    print("---CHECK RELEVANCE---")

    # Data model
    class grade(BaseModel):
        """Binary score for relevance check."""

        binary_score: str = Field(description="Relevance score 'yes' or 'no'")

    # Prompt
    prompt = PromptTemplate(
        template=DOCUMENT_GRADER_PROMPT,
        input_variables=["context", "question"],
    )

    # LLM with tool and validation
    llm_with_tool = model.with_structured_output(grade)

    # Chain
    chain = prompt | llm_with_tool

    question = state["question"]
    docs = state["documents"]
    context = "\n".join([doc.page_content for doc in docs])

    scored_result = chain.invoke({"question": question, "context": context})

    score = scored_result.binary_score

    if score == "yes":
        print("---DECISION: DOCS RELEVANT---")
        return "generate"

    else:
        print("---DECISION: DOCS NOT RELEVANT---")
        print(score)
        return "rewrite"


def retrieve_node(state: DocFinderState, config: RunnableConfig) -> dict:
    documents = vectorstore.similarity_search(state["question"])
    return {"documents": documents}


wf = StateGraph(DocFinderState)

wf.add_node("retrieve", retrieve_node)
wf.add_node("rewrite", rewrite_node)
wf.add_node("generate", generate_node)

wf.add_edge(START, "retrieve")
wf.add_conditional_edges(
    "retrieve",
    grade_documents_edge,
)
wf.add_edge("generate", END)
wf.add_edge("rewrite", "retrieve")

memory = MemorySaver()
graph = wf.compile(checkpointer=memory)
graph.name = "docfinder"
