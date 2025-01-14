import os

import ee
import lancedb
from langchain_community.vectorstores import LanceDB
from langchain_core.tools import tool
from langchain_core.tools.retriever import create_retriever_tool
from langchain_ollama import OllamaEmbeddings
from pandas import Series
from pydantic import BaseModel, Field

from zeno.agents.maingraph.models import ModelFactory
from zeno.tools.distalert.gee import init_gee

init_gee()

embedder = OllamaEmbeddings(
    model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
)
table = lancedb.connect("data/layers-context").open_table("zeno-layers-context-latest")


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

    choice: str = Field(description="Choice of context layer to use")


class ContextLayerInput(BaseModel):
    """Input schema for context layer tool"""

    question: str = Field(description="The question from the user")


model = ModelFactory().get("claude-3-5-sonnet-latest").with_structured_output(grade)


@tool(
    "context-layer-tool",
    args_schema=ContextLayerInput,
    response_format="content_and_artifact",
)
def context_layer_tool(question: str) -> dict:
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
    result = (
        results[results["name"] == results.iloc[0]["name"]]
        .sort_values(by="year", ascending=False)
        .iloc[0]
    )

    tms_url = get_tms_url(result)

    result = result.to_dict()
    result["tms_url"] = tms_url

    dataset = result.pop("dataset")

    return dataset, result


def get_tms_url(result: Series):
    if result.type == "ImageCollection":
        image = ee.ImageCollection(result.dataset).mosaic()
    else:
        image = ee.Image(result.dataset)

    # TODO: add dynamic viz parameters
    map_id = image.select(result.band).getMapId(
        visParams=result.visualization_parameters
    )

    return map_id["tile_fetcher"].url_format
