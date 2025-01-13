import datetime
from typing import List, Literal, Optional, Tuple, Union

import ee
import fiona
import googleapiclient
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from zeno.tools.contextlayer.layers import layer_choices
from zeno.tools.distalert.drivers import DRIVER_VALUEMAP, get_drivers
from zeno.tools.distalert.gee import init_gee

# Load environment variables
load_dotenv(".env")

# Initialize gee
init_gee()

gadm = fiona.open("data/gadm_410_small.gpkg")

DIST_ALERT_REF_DATE = datetime.date(2020, 12, 31)
DIST_ALERT_SCALE = 30
M2_TO_HA = 10000


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
    min_date: Optional[datetime.date] = Field(
        default=None,
        description="Cutoff date for alerts. Alerts before that date will be excluded.",
    )
    max_date: Optional[datetime.date] = Field(
        default=None,
        description="Cutoff date for alerts. Alerts after that date will be excluded.",
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


def get_date_mask(min_date: datetime.date, max_date: datetime.date) -> ee.image.Image:
    today = datetime.date.today()
    date_mask = None
    if min_date and min_date > DIST_ALERT_REF_DATE and min_date < today:
        days_passed = (today - min_date).days
        days_since_start = (today - DIST_ALERT_REF_DATE).days
        cutoff = days_since_start - days_passed
        date_mask = (
            ee.ImageCollection("projects/glad/HLSDIST/current/VEG-DIST-DATE")
            .mosaic()
            .gte(cutoff)
            .selfMask()
        )

    if max_date and max_date > DIST_ALERT_REF_DATE and max_date < today:
        days_passed = (today - max_date).days
        days_since_start = (today - DIST_ALERT_REF_DATE).days
        cutoff = days_since_start - days_passed
        date_mask_max = (
            ee.ImageCollection("projects/glad/HLSDIST/current/VEG-DIST-DATE")
            .mosaic()
            .lte(cutoff)
            .selfMask()
        )
        if date_mask:
            date_mask = date_mask.And(date_mask_max)
        else:
            date_mask = date_mask_max

    return date_mask


def get_alerts_by_landcover(
    distalerts: ee.Image,
    landcover: ee.Image,
    gee_features: ee.FeatureCollection,
    date_mask: ee.Image,
    threshold: int,
) -> Tuple[dict, ee.Image]:
    choice = [dat for dat in layer_choices if dat["dataset"] == landcover]
    if choice:
        choice = choice[0]
        if choice["type"] == "ImageCollection":
            landcover_layer = ee.ImageCollection(landcover)
        else:
            landcover_layer = ee.Image(landcover)

        if "class_table" in choice:
            class_table = choice["class_table"]
        else:
            class_table = get_class_table(choice["band"], landcover_layer)
    else:
        # TODO: replace this with a better selection. For now
        # assumes if the choice did not exist that the drivers are requested.
        landcover_layer = get_drivers()
        class_table = {val: key for key, val in DRIVER_VALUEMAP.items()}

    if choice["type"] == "ImageCollection":
        landcover_layer = landcover_layer.mosaic()

    landcover_layer = landcover_layer.select(choice["band"])

    zone_stats_img = (
        distalerts.pixelArea()
        .divide(M2_TO_HA)
        .addBands(landcover_layer)
        .updateMask(distalerts.gte(threshold))
    )
    if date_mask:
        zone_stats_img = zone_stats_img.updateMask(
            zone_stats_img.selfMask().And(date_mask)
        )

    zone_stats = zone_stats_img.reduceRegions(
        collection=gee_features,
        reducer=ee.Reducer.sum().group(groupField=1, groupName=choice["band"]),
        scale=choice["resolution"],
    ).getInfo()

    zone_stats_result = {}
    for feat in zone_stats["features"]:
        zone_stats_result[feat["properties"]["gadmid"]] = {
            class_table[dat[choice["band"]]]["name"]: dat["sum"]
            for dat in feat["properties"]["groups"]
        }
    vectorize = landcover_layer.updateMask(distalerts.gte(threshold))

    return zone_stats_result, vectorize


def get_distalerts_unfiltered(
    distalerts: ee.Image,
    gee_features: ee.FeatureCollection,
    date_mask: ee.Image,
    threshold: int,
) -> Tuple[dict, ee.Image]:
    zone_stats_img = (
        distalerts.pixelArea().divide(M2_TO_HA).updateMask(distalerts.gte(threshold))
    )
    if date_mask:
        zone_stats_img = zone_stats_img.updateMask(
            zone_stats_img.selfMask().And(date_mask)
        )

    zone_stats = zone_stats_img.reduceRegions(
        collection=gee_features,
        reducer=ee.Reducer.sum(),
        scale=DIST_ALERT_SCALE,
    ).getInfo()

    zone_stats_result = {
        feat["properties"]["gadmid"]: {"disturbances": feat["properties"]["sum"]}
        for feat in zone_stats["features"]
    }
    vectorize = (
        distalerts.gte(threshold).updateMask(distalerts.gte(threshold)).selfMask()
    )
    return zone_stats_result, vectorize


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
    min_date: Optional[datetime.date] = None,
    max_date: Optional[datetime.date] = None,
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

    date_mask = get_date_mask(min_date, max_date)

    if landcover:
        zone_stats_result, vectorize = get_alerts_by_landcover(
            distalerts=distalerts,
            landcover=landcover,
            gee_features=gee_features,
            date_mask=date_mask,
            threshold=threshold,
        )
    else:
        zone_stats_result, vectorize = get_distalerts_unfiltered(
            distalerts=distalerts,
            gee_features=gee_features,
            date_mask=date_mask,
            threshold=threshold,
        )

    # Vectorize the masked classification
    vectors = vectorize.reduceToVectors(
        geometryType="polygon",
        scale=DIST_ALERT_SCALE,
        maxPixels=1e8,
        geometry=gee_features,
        eightConnected=True,
    )

    try:
        vectorized = vectors.getInfo()
    except googleapiclient.errors.HttpError:
        vectorized = {}

    return zone_stats_result, vectorized
