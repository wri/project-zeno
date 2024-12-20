import os

import lancedb
from langchain_community.vectorstores import LanceDB
from langchain_core.tools import tool
from langchain_core.tools.retriever import create_retriever_tool
from langchain_ollama import OllamaEmbeddings
from langchain_ollama.embeddings import OllamaEmbeddings
from pydantic import BaseModel, Field

from zeno.agents.maingraph.models import ModelFactory
from zeno.tools.contextlayer.layers import DatasetNames

embedder = OllamaEmbeddings(
    model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
)
table = lancedb.connect("data/layers-context").open_table("zeno-layers-context")


# TODO: add reranker?
vectorstore = LanceDB(
    uri="data/layers-context",
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


class grade(BaseModel):
    """Choice of landcover."""

    choice: DatasetNames = Field(description="Choice of context layer to use")


class ContextLayerInput(BaseModel):
    """Input schema for context layer tool"""

    question: str = Field(description="The question from the user")


model = ModelFactory().get("claude-3-5-sonnet-latest").with_structured_output(grade)


@tool("context-layer-tool", args_schema=ContextLayerInput, return_direct=False)
def context_layer_tool(question: str) -> DatasetNames:
    """
    Determines whether the question asks for summarizing by land cover.
    """

    print("---CHECK CONTEXT LAYER TOOL---")
    embedding = embedder.embed_query(question)

    # TODO: extract hard filters from query input
    results = table.search(embedding).limit(30).to_pandas()

    # Multiple years of a single dataset are stored as separate entries
    # if the results set contains multiple datasets with the same name
    # as the top result, then we collect them all, and sort them by
    # year to return the most recent, by default
    results = (
        results[results["name"] == results.iloc[0]["name"]]
        .sort_values(by="year", ascending=False)
        .iloc[0]
    )

    # return matches.dataset.value
    return results.dataset
