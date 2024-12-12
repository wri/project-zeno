import json
import os

from langchain_core.tools import tool
from langchain_core.tools.retriever import create_retriever_tool
from langchain_community.vectorstores import LanceDB
from langchain_ollama import OllamaEmbeddings
from pydantic import BaseModel, Field

from zeno.agents.maingraph.models import ModelFactory
from zeno.tools.contextlayer.layers import DatasetNames, layer_choices

# TODO: add reranker?
vectorstore = LanceDB(
    uri="s3://zeno-static-data/layers-context",
    region="us-east-1",
    embedding=OllamaEmbeddings(
        model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
    ),
    table_name="zeno-layers-context",
)

retriever = vectorstore.as_retriever()

retriever_tool = create_retriever_tool(
    retriever,
    "retrieve_context_layers",
    "Search and return available context layers for land cover.",
)


# class grade(BaseModel):
#     """Choice of landcover."""

#     choice: DatasetNames = Field(description="Choice of context layer to use")


# class ContextLayerInput(BaseModel):
#     """Input schema for context layer tool"""

#     question: str = Field(description="The question from the user")


# model = ModelFactory().get("claude-3-5-sonnet-latest").with_structured_output(grade)


# @tool("context-layer-tool", args_schema=ContextLayerInput, return_direct=False)
# def context_layer_tool(question: str) -> DatasetNames:
#     """
#     Determines whether the question asks for summarizing by land cover.
#     """

#     print("---CHECK CONTEXT LAYER TOOL---")

#     query = (
#         f"""You are a deciding if a context layer is required for analysing disturbance alerts. \n
#     Here is the user question: {question} \n
#     If the question does not ask for grouping, return empty string. \n
#     If the question asks for grouping the disturbance alerts by landcover, decide which landcover layer is most appropriate. \n

#     The following json data gives information about the available layers. Pick the most appropriate one and return its 'dataset' value.
#     Never change the returned 'dataset' value, always return it as is. \n
#     """
#         + json.dumps(layer_choices),
#     )

#     result = model.invoke(query)

#     print(f"---DECISION: {result.choice or 'no landcover needed'}---")

#     return result.choice
