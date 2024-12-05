import os
from typing import Tuple

import fiona
from langchain_chroma.vectorstores import Chroma
from langchain_core.tools import tool
from langchain_ollama import OllamaEmbeddings
from pydantic import BaseModel, Field

gadm = fiona.open("data/gadm_410_small.gpkg")

vectorstore = Chroma(
    persist_directory="data/chroma_gadm",
    embedding_function=OllamaEmbeddings(
        model="nomic-embed-text", base_url=os.environ["OLLAMA_BASE_URL"]
    ),
    collection_name="gadm",
    create_collection_if_not_exists=False,
)


class LocationInput(BaseModel):
    """Input schema for location finder tool"""

    query: str = Field(
        description="Name of the location to search for. Can be a city, region, or country name."
    )


@tool(
    "location-tool",
    args_schema=LocationInput,
    return_direct=False,
    response_format="content_and_artifact",
)
def location_tool(query: str) -> Tuple[list, list]:
    """Find locations and their administrative hierarchies given a place name.
      Returns a list of IDs with matches at different administrative levels

    Args:
        query (str): Location name to search for

    Returns:
        matches (Tuple[list, list]): GDAM feature IDs their geojson feature collections
    """
    print("---LOCATION-TOOL---")
    matches = vectorstore.similarity_search(query, k=1)
    fids = [int(dat.metadata["fid"]) for dat in matches]
    aois = [gadm[fid] for fid in fids]
    geojson = {
        "type": "FeatureCollection",
        "features": [aoi.__geo_interface__ for aoi in aois],
    }

    return fids, geojson
