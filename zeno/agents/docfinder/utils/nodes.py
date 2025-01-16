from typing import Literal

from langchain import hub
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables.config import RunnableConfig
from pydantic import BaseModel, Field

from zeno.agents.maingraph.models import ModelFactory
from zeno.tools.docretrieve.document_retrieve_tool import retriever_tool

model_name = "claude-3-5-sonnet-latest"


def grade_documents(
    state, config: RunnableConfig
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
        template="""You are a grader assessing relevance of a retrieved document to a user question. \n
        Here is the retrieved document: \n\n {context} \n\n
        Here is the user question: {question} \n
        If the document contains keyword(s) or semantic meaning related to the user question, grade it as relevant. \n
        Give a binary score 'yes' or 'no' score to indicate whether the document is relevant to the question.""",
        input_variables=["context", "question"],
    )

    model_id = config["configurable"].get("model_id", model_name)
    model = ModelFactory().get(model_id)

    # LLM with tool and validation
    llm_with_tool = model.with_structured_output(grade)

    # Chain
    chain = prompt | llm_with_tool

    messages = state["messages"]
    last_message = messages[-1]
    docs = last_message.content

    question = state["question"]

    scored_result = chain.invoke({"question": question, "context": docs})

    score = scored_result.binary_score

    if score == "yes":
        print("---DECISION: DOCS RELEVANT---")
        return "generate"

    else:
        print("---DECISION: DOCS NOT RELEVANT---")
        print(score)
        return "rewrite"


def agent(state, config: RunnableConfig):
    """
    Invokes the agent model to generate a response based on the current state. Given
    the question, it will decide to retrieve using the retriever tool, or simply end.

    Args:
        state (messages): The current state

    Returns:
        dict: The updated state with the agent response appended to messages
    """
    print("---CALL DOCFINDER---")
    messages = [HumanMessage(content=state["question"])]

    model_id = config["configurable"].get("model_id", model_name)
    model = ModelFactory().get(model_id)

    model = model.bind_tools([retriever_tool])
    response = model.invoke(messages)
    # We return a list, because this will get added to the existing list
    return {"messages": [response]}


def rewrite(state, config: RunnableConfig):
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
            content=f""" \n
    Look at the input and try to reason about the underlying semantic intent / meaning. \n
    Here is the initial question:
    \n ------- \n
    {question}
    \n ------- \n
    Formulate an improved question: """,
        )
    ]
    model_id = config["configurable"].get("model_id", model_name)
    model = ModelFactory().get(model_id)

    # Grader
    response = model.invoke(msg)
    return {"question": response.content}


def generate(state, config: RunnableConfig):
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
    print("GENERATING FROM", last_message.content)

    docs = last_message.content

    # Prompt
    prompt = hub.pull("rlm/rag-prompt")

    model_id = config["configurable"].get("model_id", model_name)
    model = ModelFactory().get(model_id)

    # Chain
    rag_chain = prompt | model

    # Run
    response = rag_chain.invoke({"context": docs, "question": question})
    return {"messages": [response], "route": "docfinder"}
