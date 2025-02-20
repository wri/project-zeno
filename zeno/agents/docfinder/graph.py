from typing import Literal

from langchain import hub
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from zeno.agents.docfinder.agent import docfinder_agent, tools
from zeno.agents.docfinder.prompts import (
    DOC_FINDER_PROMPT,
    DOCUMENT_GRADER_PROMPT,
    QUERY_OPTIMIZER_PROMPT,
)
from zeno.agents.docfinder.state import DocFinderState

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
    messages = state["messages"]
    question = state["question"]
    last_message = messages[-1]

    docs = last_message.content

    # Prompt
    prompt = hub.pull("rlm/rag-prompt")
    # Chain
    rag_chain = prompt | model | StrOutputParser()

    # Run
    response = rag_chain.invoke({"context": docs, "question": question})
    return {"messages": [AIMessage(content=response)]}


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

    messages = state["messages"]
    last_message = messages[-1]

    question = state["question"]
    docs = last_message.content

    scored_result = chain.invoke({"question": question, "context": docs})

    score = scored_result.binary_score

    if score == "yes":
        print("---DECISION: DOCS RELEVANT---")
        return "generate"

    else:
        print("---DECISION: DOCS NOT RELEVANT---")
        print(score)
        return "rewrite"


def handle_tool_error(state: DocFinderState) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


def create_tool_node_with_fallback(tools: list) -> dict:
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


def docfinder_node(state: DocFinderState, config: RunnableConfig) -> dict:
    doc_finder_prompt = SystemMessage(content=DOC_FINDER_PROMPT)
    result = docfinder_agent.invoke(
        [doc_finder_prompt, HumanMessage(state["question"])], config
    )

    return {"messages": [result]}


retrieve_node = create_tool_node_with_fallback(tools)

wf = StateGraph(DocFinderState)

wf.add_node("docfinder", docfinder_node)
wf.add_node("retrieve", retrieve_node)
wf.add_node("rewrite", rewrite_node)
wf.add_node("generate", generate_node)

wf.add_edge(START, "docfinder")
wf.add_conditional_edges(
    "docfinder",
    tools_condition,
    {
        "tools": "retrieve",
        END: END,
    },
)
wf.add_conditional_edges(
    "retrieve",
    grade_documents_edge,
)
wf.add_edge("generate", END)
wf.add_edge("rewrite", "docfinder")

memory = MemorySaver()
graph = wf.compile(checkpointer=memory)
graph.name = "docfinder"
