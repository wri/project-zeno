import os
from typing import Tuple

import requests
import fiona
import duckdb
from langchain_chroma.vectorstores import Chroma
from langchain_core.tools import tool
from langchain_ollama import OllamaEmbeddings
from pydantic import BaseModel, Field

from dotenv import load_dotenv

load_dotenv()

class LocationInput(BaseModel):
    """Input schema for location finder tool"""

    query: str = Field(
        description="Name of the location to search for. Can be a city, region, or country name. Each of these values separated by commas"
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
        query (str): Location name to search for, different parts of the string separated by commas

    Returns:
        matches (Tuple[list, list]): GDAM feature IDs their geojson feature collections
    """
    print("---LOCATION-TOOL---")
    url = f"https://api.opencagedata.com/geocode/v1/json?q={query}&key={os.environ.get('OPENCAGE_API_KEY')}"
    print(url)

    response = requests.get(url)
    lat = response.json()["results"][0]["geometry"]["lat"]
    lon = response.json()["results"][0]["geometry"]["lng"]

    overture = duckdb.sql(
        f"""INSTALL httpfs; INSTALL spatial;
    LOAD spatial; -- noqa
    LOAD httpfs;  -- noqa
    -- Access the data on AWS in this example
    SET s3_region='us-west-2';

    SELECT
    subtype, names, division_id, ST_AsGeoJSON(geometry)
    FROM
    --'/Users/tam/Desktop/overture_division_area/*.parquet'
    read_parquet('s3://overturemaps-us-west-2/release/2024-12-18.0/theme=divisions/type=division_area/*', filename=true, hive_partitioning=1)
    WHERE bbox.xmin < {lon}
    AND   bbox.xmax > {lon}
    AND   bbox.ymin < {lat}
    AND   bbox.ymax > {lat}
    AND ST_Intersects(geometry, ST_Point({lon}, {lat}))
    LIMIT 3;
    """
    )
    print(overture)






    matches = vectorstore.similarity_search(query, k=3)
    fids = [int(dat.metadata["fid"]) for dat in matches]
    aois = [gadm[fid] for fid in fids]
    geojson = {
        "type": "FeatureCollection",
        "features": [aoi.__geo_interface__ for aoi in aois],
    }

    return fids, geojson
