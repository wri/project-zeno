import datetime
import json
from pathlib import Path
from typing import Literal, Optional, Tuple

import ee
import geopandas as gpd
import googleapiclient
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from pyproj import CRS

from zeno.agents.distalert.drivers import DRIVER_VALUEMAP, get_drivers, GEE_FOLDER
from zeno.agents.distalert.gee import init_gee
from zeno.agents.distalert.tool_context_layer import (
    table as contextfinder_table,
)

load_dotenv(".env")
init_gee()

DIST_ALERT_REF_DATE = datetime.date(2020, 12, 31)
DIST_ALERT_STATS_SCALE = 30
DIST_ALERT_VECTORIZATION_SCALE = 150


class DistAlertsInput(BaseModel):
    """Input schema for dist tool"""

    name: str = Field(description="Name of the area of interest")
    gadm_id: str = Field(description="GADM ID of the area of interest")
    gadm_level: int = Field(description="GADM level of the area of interest")
    min_date: datetime.date = Field(
        description="Cutoff date for alerts. Alerts before that date will be excluded.",
    )
    max_date: datetime.date = Field(
        description="Cutoff date for alerts. Alerts after that date will be excluded.",
    )
    context_layer_name: Optional[str] = Field(
        default=None,
        description="Context layer name to group zonal statistics by.",
    )
    threshold: Optional[Literal[1, 2, 3, 4, 5, 6, 7, 8]] = Field(
        default=5, description="Threshold for disturbance alert scale"
    )
    buffer_distance: Optional[float] = Field(
        default=None,
        description="Buffer distance in meters for buffering the features.",
    )


def get_date_mask(min_date: datetime.date, max_date: datetime.date) -> ee.image.Image:
    today = datetime.date.today()
    date_mask = None
    if min_date and min_date > DIST_ALERT_REF_DATE and min_date < today:
        days_passed = (today - min_date).days
        days_since_start = (today - DIST_ALERT_REF_DATE).days
        cutoff = days_since_start - days_passed
        date_mask = (
            ee.ImageCollection(GEE_FOLDER + "VEG-DIST-DATE")
            .mosaic()
            .gte(cutoff)
            .selfMask()
        )

    if max_date and max_date > DIST_ALERT_REF_DATE and max_date < today:
        days_passed = (today - max_date).days
        days_since_start = (today - DIST_ALERT_REF_DATE).days
        cutoff = days_since_start - days_passed
        date_mask_max = (
            ee.ImageCollection(GEE_FOLDER + "VEG-DIST-DATE")
            .mosaic()
            .lte(cutoff)
            .selfMask()
        )
        if date_mask:
            date_mask = date_mask.And(date_mask_max)
        else:
            date_mask = date_mask_max

    return date_mask


def get_context_layer_info(dataset: str) -> dict:
    data = contextfinder_table.search().where(f"dataset = '{dataset}'").to_list()
    if not data:
        return {}
    data.reverse()
    data = data[0]
    data["visualization_parameters"] = json.loads(data["visualization_parameters"])
    data["metadata"] = json.loads(data["metadata"])
    data.pop("vector")

    return data


def get_zone_stats(
    context_layer, distalerts, threshold, date_mask, gee_features, choice
):
    zone_stats_img = (
        distalerts
        .addBands(context_layer)
        .updateMask(distalerts.gte(threshold))
    )

    if date_mask:
        zone_stats_img = zone_stats_img.updateMask(
            zone_stats_img.selfMask().And(date_mask)
        )

    return zone_stats_img.reduceRegions(
        collection=gee_features,
        reducer=ee.Reducer.count().group(groupField=1, groupName=choice["band"]),
        scale=choice["resolution"],
    ).getInfo(), zone_stats_img.select(choice["band"])


def get_alerts_by_context_layer(
    name: str,
    distalerts: ee.Image,
    context_layer_name: ee.Image,
    gee_features: ee.FeatureCollection,
    date_mask: ee.Image,
    threshold: int,
) -> Tuple[dict, ee.Image]:
    choice = get_context_layer_info(context_layer_name)

    # Note: the ee_excpetion.EEXception that is triggered when an Image type
    # is loaded as an ImageCollection (or inversely) is actually raised in
    # the `getinfo()` call (I assume due to some internal lazy-loading logic).
    # I've moved the `getInfo()` call to a separate method in order to avoid
    # re-defining the functionality in the except block.
    if choice:
        try:
            context_layer = (
                ee.ImageCollection(context_layer_name).mosaic().select(choice["band"])
            )
            zone_stats, vectorize = get_zone_stats(
                context_layer, distalerts, threshold, date_mask, gee_features, choice
            )
        except ee.ee_exception.EEException:
            context_layer = ee.Image(context_layer_name).select(choice["band"])
            zone_stats, vectorize = get_zone_stats(
                context_layer, distalerts, threshold, date_mask, gee_features, choice
            )

    else:
        context_layer = get_drivers()
        # TODO: replace this with layer in DB, this is currently a patch to make the tests work
        choice["resolution"] = DIST_ALERT_STATS_SCALE
        choice["band"] = "driver"
        choice["metadata"] = {
            "value_mappings": [
                {"value": val, "description": key}
                for key, val in DRIVER_VALUEMAP.items()
            ]
        }
        zone_stats, vectorize = get_zone_stats(
            context_layer, distalerts, threshold, date_mask, gee_features, choice
        )

    zone_stats = zone_stats["features"][0]["properties"]["groups"]

    value_mappings = {
        dat["value"]: dat["description"] for dat in choice["metadata"]["value_mappings"]
    }
    zone_stats = {value_mappings[dat[choice["band"]]]: dat["count"] for dat in zone_stats}

    return zone_stats, vectorize


def get_distalerts_unfiltered(
    name: str,
    distalerts: ee.Image,
    gee_features: ee.FeatureCollection,
    date_mask: ee.Image,
    threshold: int,
) -> Tuple[dict, ee.Image]:
    zone_stats_img = (
        distalerts.updateMask(distalerts.gte(threshold))
    )
    if date_mask:
        zone_stats_img = zone_stats_img.updateMask(
            zone_stats_img.selfMask().And(date_mask)
        )

    zone_stats = zone_stats_img.reduceRegions(
        collection=gee_features,
        reducer=ee.Reducer.count(),
        scale=DIST_ALERT_STATS_SCALE,
    ).getInfo()

    zone_stats_result = {"disturbances": sum(feat["properties"]["count"] for feat in zone_stats["features"])}

    return zone_stats_result, zone_stats_img


def detect_utm_zone(lat, lon):
    """
    Detect the UTM zone for a given latitude and longitude in WGS84.
    """
    zone_number = int((lon + 180) // 6) + 1
    hemisphere = "north" if lat >= 0 else "south"
    utm_crs = CRS.from_dict(
        {"proj": "utm", "zone": zone_number, "south": hemisphere == "south"}
    )
    return utm_crs


def get_features(
    gadm_id: str, gadm_level: int, buffer_distance: float
) -> ee.FeatureCollection:
    aoi_df = gpd.read_file(
        Path("data") / f"gadm_410_level_{gadm_level}.gpkg",
        where=f"GID_{gadm_level} like '{gadm_id}'",
    )
    aoi = aoi_df.geometry.iloc[0]

    if buffer_distance:
        utm = detect_utm_zone(aoi.centroid.y, aoi.centroid.x)
        aoi_df_utm = aoi_df.to_crs(utm)
        aoi = aoi_df_utm.buffer(buffer_distance).to_crs(aoi_df.crs).iloc[0]

    return ee.FeatureCollection([ee.Feature(aoi.__geo_interface__)])


@tool(
    "dist-alerts-tool",
    args_schema=DistAlertsInput,
    return_direct=True,
    response_format="content_and_artifact",
)
def dist_alerts_tool(
    name: str,
    gadm_id: str,
    gadm_level: int,
    min_date: datetime.date,
    max_date: datetime.date,
    context_layer_name: Optional[str] = None,
    threshold: Optional[Literal[1, 2, 3, 4, 5, 6, 7, 8]] = 5,
    buffer_distance: Optional[float] = None,
) -> dict:
    """
    Dist alerts tool

    This tool quantifies vegetation disturbance alerts over an area of interest
    and summarizes the alerts in statistics by context layer types.

    The unit of disturbances that are returned are numberr of pixels with
    potential disturbances.
    """
    print("---DIST ALERTS TOOL---")

    gee_features = get_features(
        gadm_id=gadm_id, gadm_level=gadm_level, buffer_distance=buffer_distance
    )
    distalerts = ee.ImageCollection(GEE_FOLDER + "VEG-DIST-STATUS").mosaic()

    date_mask = get_date_mask(min_date, max_date)

    if context_layer_name:
        zone_stats_result, vectorize = get_alerts_by_context_layer(
            name=name,
            distalerts=distalerts,
            context_layer_name=context_layer_name,
            gee_features=gee_features,
            date_mask=date_mask,
            threshold=threshold,
        )
    else:
        zone_stats_result, vectorize = get_distalerts_unfiltered(
            name=name,
            distalerts=distalerts,
            gee_features=gee_features,
            date_mask=date_mask,
            threshold=threshold,
        )

    if sum(zone_stats_result.values()) < 5000:
        scale = DIST_ALERT_STATS_SCALE
    else:
        scale = DIST_ALERT_VECTORIZATION_SCALE

    # Vectorize the masked classification
    vectors = vectorize.reduceToVectors(
        geometryType="polygon",
        scale=scale,
        maxPixels=1e8,
        geometry=gee_features,
        eightConnected=True,
    )

    try:
        vectorized = vectors.getInfo()
    except:
        vectorized = {}

    if not vectorized.get("features"):
        vectorized = {}

    return zone_stats_result, vectorized
