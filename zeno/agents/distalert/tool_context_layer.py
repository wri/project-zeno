import os
from pathlib import Path
import json

import ee
import lancedb
from langchain_core.tools import tool
from langchain_ollama import OllamaEmbeddings
from pandas import Series
from pydantic import BaseModel, Field

from zeno.agents.distalert.gee import init_gee

init_gee()
data_dir = Path("data")


embedder = OllamaEmbeddings(
    model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
)


table = lancedb.connect(data_dir / "layers-context").open_table(
    "zeno-layers-context-latest"
)


def get_tms_url(result: Series):
    try:
        image = ee.ImageCollection(result.dataset).mosaic()
    except ee.ee_exception.EEException:
        image = ee.Image(result.dataset)

    if result.visualization_parameters:
        viz_params = json.loads(result.visualization_parameters)
        map_id = image.select(result.band).getMapId(viz_params)
    else:
        map_id = image.select(result.band).getMapId()

    return map_id["tile_fetcher"].url_format


class ContextLayerInput(BaseModel):
    """Input schema for context layer tool"""

    question: str = Field(description="landcover layer requested by the user")


@tool(
    "context-layer-tool",
    args_schema=ContextLayerInput,
    response_format="content_and_artifact",
)
def context_layer_tool(question: str) -> dict:
    """
    Finds the most relevant landcover layer for the user's question.
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

    # Delete the dataset key vector as ndarray is not serializable
    del result["vector"]

    dataset = result.pop("dataset")

    return dataset, result
