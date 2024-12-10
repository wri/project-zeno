from typing import List, Literal, Optional, Union

import ee
import fiona
import googleapiclient
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from zeno.tools.contextlayer.layers import layer_choices
from zeno.tools.distalert.gee import init_gee

# Load environment variables
load_dotenv(".env")

# Initialize gee
init_gee()

gadm = fiona.open("data/gadm_410_small.gpkg")


class DistAlertsInput(BaseModel):
    """Input schema for dist tool"""

    features: List[int] = Field(
        description="List of GADM ids are used for zonal statistics"
    )
    landcover: Optional[str] = Field(
        default=None, description="Landcover layer name to group zonal statistics by"
    )
    threshold: Optional[Literal[1, 2, 3, 4, 5, 6, 7, 8]] = Field(
        default=5, description="Threshold for disturbance alert scale"
    )


def print_meta(
    layer: Union[ee.image.Image, ee.imagecollection.ImageCollection]
) -> None:
    """Print layer metadata"""
    # Get all metadata as a dictionary
    metadata = layer.getInfo()

    # Print metadata
    print("Image Metadata:")
    for key, value in metadata.items():
        print(f"{key}: {value}")


def get_class_table(
    band_name: str, layer: Union[ee.image.Image, ee.imagecollection.ImageCollection]
) -> dict:
    band_info = layer.select(band_name).getInfo()

    names = band_info["features"][0]["properties"][f"{band_name}_class_names"]
    values = band_info["features"][0]["properties"][f"{band_name}_class_values"]
    colors = band_info["features"][0]["properties"][f"{band_name}_class_palette"]

    pairs = []
    for name, color in zip(names, colors):
        pairs.append({"name": name, "color": color})

    return {val: pair for val, pair in zip(values, pairs)}


@tool(
    "dist-alerts-tool",
    args_schema=DistAlertsInput,
    return_direct=True,
    response_format="content_and_artifact",
)
def dist_alerts_tool(
    features: List[str],
    landcover: Optional[str] = None,
    threshold: Optional[Literal[1, 2, 3, 4, 5, 6, 7, 8]] = 5,
) -> dict:
    """
    Dist alerts tool

    This tool quantifies vegetation disturbance alerts over an area of interest
    and summarizes the alerts in statistics by landcover types.
    """
    print("---DIST ALERTS TOOL---")
    distalerts = ee.ImageCollection(
        "projects/glad/HLSDIST/current/VEG-DIST-STATUS"
    ).mosaic()

    gee_features = ee.FeatureCollection(
        [ee.Feature(gadm[int(id)].__geo_interface__) for id in features]
    )

    combo = distalerts.gte(threshold)

    if landcover:
        choice = [dat for dat in layer_choices if dat["dataset"] == landcover][0]
        if choice["type"] == "ImageCollection":
            landcover_layer = ee.ImageCollection(landcover)  # .mosaic()
        else:
            landcover_layer = ee.Image(landcover)

        class_table = get_class_table(choice["band"], landcover_layer)

        if choice["type"] == "ImageCollection":
            landcover_layer = landcover_layer.mosaic()

        landcover_layer = landcover_layer.select(choice["band"])

        combo = combo.addBands(landcover_layer)
        zone_stats = combo.reduceRegions(
            collection=gee_features,
            reducer=ee.Reducer.count().group(groupField=1, groupName=choice["band"]),
            scale=choice["resolution"],
        ).getInfo()
        zone_stats_result = {}
        for feat in zone_stats["features"]:
            zone_stats_result[feat["properties"]["gadmid"]] = {
                class_table[dat[choice["band"]]]["name"]: dat["count"]
                for dat in feat["properties"]["groups"]
            }
        vectorize = landcover_layer.updateMask(distalerts.gte(threshold).selfMask())
    else:
        zone_stats = (
            distalerts.gte(threshold)
            .selfMask()
            .reduceRegions(
                collection=gee_features,
                reducer=ee.Reducer.count(),
                scale=30,
            )
            .getInfo()
        )
        zone_stats_result = {
            feat["properties"]["gadmid"]: {"disturbances": feat["properties"]["count"]}
            for feat in zone_stats["features"]
        }
        vectorize = distalerts.gte(threshold).selfMask()

    # Vectorize the masked classification
    vectors = vectorize.reduceToVectors(
        geometryType="polygon",
        scale=30,
        maxPixels=1e8,
        geometry=gee_features,
        eightConnected=True,
    )

    try:
        vectorized = vectors.getInfo()
    except googleapiclient.errors.HttpError:
        vectorized = {}

    return zone_stats_result, vectorized
