
import ee
import json
import googleapiclient
from typing import Union, List
from shapely import Polygon
import pydantic
import os
from typing import Optional, Literal
from urllib.parse import quote
import pandas as pd
import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from zeno.tools.distalert.gee import init_gee
from geojson_pydantic import FeatureCollection
import geopandas as gpd
from zeno.tools.location.location_matcher import LocationMatcher
# Load environment variables
load_dotenv(".env")

# Initialize gee
init_gee()

location_matcher = LocationMatcher("data/gadm41_PRT.gpkg")


class DistAlertsInput(BaseModel):
    """Input schema for dist tool"""
    # class Config:
    #     arbitrary_types_allowed = True
    features: List[str] = Field(description="List of GADM ids are used for zonal statistics")
    # features: FeatureCollection = Field(description="Feature collection that is used for zonal statistics")
    landcover: Optional[str] = Field(default=None, description="Landcover layer name to group zonal statistics by")
    threshold: Optional[Literal[1, 2, 3, 4, 5, 6, 7, 8]] = Field(default=5, description="Threshold for disturbance alert scale")


def print_meta(layer: Union[ee.image.Image, ee.imagecollection.ImageCollection]) -> None:
    """Print layer metadata"""
    # Get all metadata as a dictionary
    metadata = layer.getInfo()

    # Print metadata
    print("Image Metadata:")
    for key, value in metadata.items():
        print(f"{key}: {value}")


@tool(
    "dist-alerts-tool", args_schema=DistAlertsInput, return_direct=True, response_format="content_and_artifact",
)
def dist_alerts_tool(features: List[str], landcover: Optional[str]=None, threshold: Optional[Literal[1, 2, 3, 4, 5, 6, 7, 8]]=5) -> dict:
    """
    Dist alerts tool
    
    This tool quantifies vegetation disturbance alerts over an area of interest
    and summarizes the alerts in statistics by landcover types.
    """
    print("---DIST ALERTS TOOL---")
    distalerts = ee.ImageCollection("projects/glad/HLSDIST/current/VEG-DIST-STATUS").mosaic()

    gee_features = ee.FeatureCollection([ee.FeatureCollection(location_matcher.get_by_id(id)) for id in features])
    gee_features = gee_features.flatten()

    combo = distalerts.gte(threshold)

    if landcover:
        landcover_layer = ee.Image(landcover).select("classification")
        combo = combo.addBands(landcover_layer)
        zone_stats = combo.reduceRegions(
            collection=gee_features,
            reducer=ee.Reducer.count().group(groupField=1, groupName="classification"),
            scale=30,
        ).getInfo()
        zone_stats_result = {
           feat["properties"]["GID_3"]: feat["properties"]["groups"] for feat in zone_stats["features"]
        }
        vectorize = landcover_layer.updateMask(distalerts.gte(threshold).selfMask())
    else:
        zone_stats = distalerts.gte(threshold).selfMask().reduceRegions(
            collection=gee_features,
            reducer=ee.Reducer.count(),
            scale=30,
        ).getInfo()
        zone_stats_result = {
           feat["properties"]["GID_3"]: [{"classification": 1, "count": feat["properties"]["count"]}] for feat in zone_stats["features"]
        }
        vectorize = distalerts.gte(threshold).selfMask()


    # Vectorize the masked classification
    vectors = vectorize.reduceToVectors(
        geometryType='polygon',
        scale=100,
        maxPixels=1e8,
        geometry=gee_features,
        eightConnected=True,
    )

    try:
        vectorized = vectors.getInfo()
    except googleapiclient.errors.HttpError:
        vectorized = {}

    return zone_stats_result, vectorized
