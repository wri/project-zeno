from typing import Literal, Optional

from langchain_core.prompts import PromptTemplate
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from zeno.agents.maingraph.models import ModelFactory


class grade(BaseModel):
    """Binary score for relevance check."""

    binary_score: Literal["yes", "no"] = Field(
        description="Relevance score 'yes' or 'no'"
    )


prompt = PromptTemplate(
    template="""You are a deciding if a context layer is required for analysing disturbance alerts. \n
    Here is the user question: {question} \n
    If the question asks for grouping the disturbance alerts by landcover, decide in favor of using a context layer. \n
    Give a binary score 'yes' or 'no' score to indicate whether a landcover layer should be used.""",
    input_variables=["question"],
)


class ContextLayerInput(BaseModel):
    """Input schema for context layer tool"""

    question: str = Field(description="The question from the user")


model = ModelFactory().get("claude-3-5-sonnet-latest").with_structured_output(grade)

chain = prompt | model


@tool("context-layer-tool", args_schema=ContextLayerInput, return_direct=False)
def context_layer_tool(question: str) -> Optional[str]:
    """
    Determines whether the question asks for summarizing by land cover.
    """

    print("---CHECK CONTEXT LAYER TOOL---")

    scored_result = chain.invoke({"question": question})

    score = scored_result.binary_score

    if score == "yes":
        print("---DECISION: USE LANDCOVER---")
        return "WRI/SBTN/naturalLands/v1/2020"
    elif score == "no":
        print("---DECISION: DONT USE LANDCOVER---")
        return None
    else:
        raise ValueError(f"score was not yes or no, it was {score}")
