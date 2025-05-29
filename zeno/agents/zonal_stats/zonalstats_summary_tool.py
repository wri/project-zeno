import json
from datetime import datetime
from typing import Dict, Union

import boto3
import numpy as np
import rasterio
from pystac_client import Client
from rasterio.mask import mask
from rasterio.session import AWSSession
from shapely.geometry import shape
from stackstac import stack
from pydantic import BaseModel
from langchain.chains import LLMChain
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.tools import tool

NL_classification_values = {
    2: "natural forests", 3: "natural short vegetation", 4: "natural water", 5: "mangroves",
    6: "bare", 7: "snow", 8: "wet natural forests", 9: "natural peat forests",
    10: "wet natural short vegetation", 11: "natural peat short vegetation", 12: "crop",
    13: "built", 14: "non-natural tree cover", 15: "non-natural short vegetation",
    16: "non-natural water", 17: "wet non-natural tree cover", 18: "non-natural peat tree cover",
    19: "wet non-natural short vegetation", 20: "non-natural peat short vegetation", 21: "non-natural bare"
}

DEFAULT_COG_PATH = "s3://gfw-data-lake/umd_glad_dist_alerts/v20250329/raster/epsg-4326/cog/default.tif"
INTENSITY_COG_PATH = "s3://gfw-data-lake/umd_glad_dist_alerts/v20250329/raster/epsg-4326/cog/intensity.tif"
STAC_API_URL = "https://eoapi.zeno-staging.ds.io/stac"
AWS_PROFILE = "zeno_internal_sso"
REFERENCE_DATE = datetime(2015, 1, 1)


class ParsedParams(BaseModel):
    start_date: str
    end_date: str
    confidence_threshold: float
    intensity_threshold: int
    aoi: Union[str, Dict]  # Named region or GeoJSON


def convert_date_range_to_days(date_range):
    start_date = datetime.strptime(date_range[0][:10], "%Y-%m-%d")
    end_date = datetime.strptime(date_range[1][:10], "%Y-%m-%d")
    return (start_date - REFERENCE_DATE).days, (end_date - REFERENCE_DATE).days, start_date, end_date

def load_alert_data(geometry):
    session = boto3.Session(profile_name=AWS_PROFILE)
    with rasterio.Env(AWSSession(session), AWS_REQUEST_PAYER="requester"):
        with rasterio.open(DEFAULT_COG_PATH) as src1:
            default_data, _ = mask(src1, geometry, crop=True)
        with rasterio.open(INTENSITY_COG_PATH) as src2:
            intensity_data, _ = mask(src2, geometry, crop=True)
    return default_data[0], intensity_data[0]

def load_natural_lands_mosaic(aoi_geom, start_date, end_date):
    stac = Client.open(STAC_API_URL)
    items = list(stac.search(
        collections=["natural-lands-map-v1-1"],
        intersects=aoi_geom,
        datetime=f"{start_date.date()}/{end_date.date()}",
        max_items=50
    ).get_items())

    if not items:
        raise ValueError("No Natural Lands items found for AOI.")

    da = stack(items, bounds_latlon=aoi_geom.bounds, snap_bounds=True, epsg=4326).chunk({"x": 1024, "y": 1024})
    return da.astype("int16").max("time").squeeze() if "time" in da.dims else da.squeeze()

def parse_input_message(input_text: str) -> ParsedParams:
    prompt = PromptTemplate(
        input_variables=["input_text"],
        template="""
Extract the following parameters from the input text:
- start_date (YYYY-MM-DD)
- end_date (YYYY-MM-DD)
- confidence_threshold (float)
- intensity_threshold (int)
- aoi (GeoJSON object)

Input:
{input_text}

Return a JSON object with only those keys. Output only valid JSON.
"""
    )
    llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)
    chain = LLMChain(llm=llm, prompt=prompt)
    response = chain.run(input_text=input_text)

    try:
        return ParsedParams(**json.loads(response))
    except json.JSONDecodeError:
        raise ValueError(f"Could not parse JSON:\n{response}")


@tool
def summarize_zonal_alerts(input_text: str) -> Dict:
    """Given instructions about an AOI, date ranges and thresholds, returns filtered zonal stats by natural land class."""

    parsed = parse_input_message(input_text)
    print("parsed: ", parsed)
    print(parsed.aoi)
    #geometry = [shape(parsed.aoi["geometry"])]
    geometry = [shape(parsed.aoi)]
    start_days, end_days, start_date, end_date = convert_date_range_to_days((parsed.start_date, parsed.end_date))

    encoded, intensities = load_alert_data(geometry)
    confidence = encoded // 10000
    days_since_2015 = encoded % 10000
    max_days = (datetime.today() - REFERENCE_DATE).days

    days_since_2015[days_since_2015 == 9999] = days_since_2015[days_since_2015 < 9999].max()

    land_cover = load_natural_lands_mosaic(shape(parsed.aoi["geometry"]), start_date, end_date)
    if land_cover.shape != confidence.shape:
        raise ValueError(f"Shape mismatch: {land_cover.shape} vs {confidence.shape}")

    valid_mask = (
        (confidence >= parsed.confidence_threshold) &
        (days_since_2015 >= start_days) &
        (days_since_2015 <= end_days) &
        (days_since_2015 < max_days) &
        (intensities >= parsed.intensity_threshold)
    )

    results = {}
    valid_lc = land_cover.values[valid_mask]
    unique_classes, counts = np.unique(valid_lc, return_counts=True)
    for cls, count in zip(unique_classes, counts):
        results[int(cls)] = {
            "class": NL_classification_values.get(int(cls), "Unknown"),
            "count": int(count)
        }

    return {
        "start_date": parsed.start_date,
        "end_date": parsed.end_date,
        "current_max_days_possible_based_on_today": max_days,
        "current_min_days_since_2015_in_aoi": days_since_2015.min(),
        "current_max_days_since_2015_in_aoi": days_since_2015.max(),
        "confidence_threshold": parsed.confidence_threshold,
        "intensity_threshold": parsed.intensity_threshold,
        "results": results
    }

