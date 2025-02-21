from typing import Annotated, List, Sequence

from langchain_core.documents.base import Document
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from typing_extensions import TypedDict


class DocFinderState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    question: str
    documents: List[Document]
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps
