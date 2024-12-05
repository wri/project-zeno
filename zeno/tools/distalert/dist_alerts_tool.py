from typing import List, Literal, Optional, Union

import ee
import fiona
import googleapiclient
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from zeno.tools.distalert.gee import init_gee

# Load environment variables
load_dotenv(".env")

# Initialize gee
init_gee()

gadm = fiona.open("data/gadm_410_small.gpkg")

classtables = {
    "WRI/SBTN/naturalLands/v1/2020": {
        2: {"color": "#246E24", "description": "natural forests"},
        3: {"color": "#B9B91E", "description": "natural short vegetation"},
        4: {"color": "#6BAED6", "description": "natural water"},
        5: {"color": "#06A285", "description": "mangroves"},
        6: {"color": "#FEFECC", "description": "bare"},
        7: {"color": "#ACD1E8", "description": "snow"},
        8: {"color": "#589558", "description": "wet natural forests"},
        9: {"color": "#093D09", "description": "natural peat forests"},
        10: {"color": "#DBDB7B", "description": "wet natural short vegetation"},
        11: {"color": "#99991A", "description": "natural peat short vegetation"},
        12: {"color": "#D3D3D3", "description": "crop"},
        13: {"color": "#D3D3D3", "description": "built"},
        14: {"color": "#D3D3D3", "description": "non-natural tree cover"},
        15: {"color": "#D3D3D3", "description": "non-natural short vegetation"},
        16: {"color": "#D3D3D3", "description": "non-natural water"},
        17: {"color": "#D3D3D3", "description": "wet non-natural tree cover"},
        18: {"color": "#D3D3D3", "description": "non-natural peat tree cover"},
        19: {"color": "#D3D3D3", "description": "wet non-natural short vegetation"},
        20: {"color": "#D3D3D3", "description": "non-natural peat short vegetation"},
        21: {"color": "#D3D3D3", "description": "non-natural bare"},
    }
}


class DistAlertsInput(BaseModel):
    """Input schema for dist tool"""

    # class Config:
    #     arbitrary_types_allowed = True
    features: List[str] = Field(
        description="List of GADM ids are used for zonal statistics"
    )
    # features: FeatureCollection = Field(description="Feature collection that is used for zonal statistics")
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
        class_table = classtables[landcover]
        landcover_layer = ee.Image(landcover).select("classification")
        combo = combo.addBands(landcover_layer)
        zone_stats = combo.reduceRegions(
            collection=gee_features,
            reducer=ee.Reducer.count().group(groupField=1, groupName="classification"),
            scale=30,
        ).getInfo()
        zone_stats_result = {}
        for feat in zone_stats["features"]:
            zone_stats_result[feat["properties"]["gadmid"]] = {
                class_table[dat["classification"]]["description"]: dat["count"]
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
