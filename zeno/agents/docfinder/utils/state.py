import operator
from typing_extensions import TypedDict
from typing import List, Annotated
from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage


class GraphState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
    question: str  # User question
    generation: str  # LLM generation
    answers: int  # Number of answers generated
    loop_step: Annotated[int, operator.add]
    documents: List[str]  # List of retrieved documents
