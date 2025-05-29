from datetime import datetime

import dotenv
from datasets.utils import load_stac_data_to_db
from pystac import (
    Collection,
    Extent,
    Item,
    Provider,
    ProviderRole,
    SpatialExtent,
    TemporalExtent,
    set_stac_version,
)
from rio_stac import create_stac_item

dotenv.load_dotenv("stac/env/.env_localhost")

set_stac_version("1.1.0")

COLLECTION_ID = "dist-alerts"


def create_dist_items() -> list[Item]:
    url = "s3://gfw-data-lake/umd_glad_dist_alerts/v20250329/raster/epsg-4326/cog/default.tif"
    default_item = create_stac_item(
        source=url,
        id="dist-alerts-default",
        collection=COLLECTION_ID,
        with_raster=True,
        with_proj=True,
        properties={
            "start_datetime": str(datetime(2015, 1, 1)),
            "end_datetime": str(datetime(2025, 4, 30)),
        },
    )

    url = "s3://gfw-data-lake/umd_glad_dist_alerts/v20250329/raster/epsg-4326/cog/intensity.tif"
    intensity_item = create_stac_item(
        source=url,
        id="dist-alerts-intensity",
        collection=COLLECTION_ID,
        with_raster=True,
        with_proj=True,
        properties={
            "start_datetime": str(datetime(2015, 1, 1)),
            "end_datetime": str(datetime(2025, 4, 30)),
        },
    )

    return [default_item, intensity_item]


def create_collection() -> Collection:
    spatial_extent = SpatialExtent(bboxes=[[-180, -60, 180, 75]])
    temporal_extent = TemporalExtent(
        intervals=[[datetime(2015, 1, 1), datetime(2025, 4, 30)]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )

    return Collection(
        id=COLLECTION_ID,
        description="""This dataset is a derivative of the OPERA’s DIST-ALERT product (OPERA Land Surface Disturbance Alert from Harmonized Landsat Sentinel-2 product), which is derived through a time-series analysis of harmonized data from the NASA/USGS Landsat and ESA Sentinel-2 satellites (known as the HLS dataset). The product identifies and continuously monitors vegetation cover change in 30-m pixels across the globe. It can be accessed through the LPDAAC website here: https://search.earthdata.nasa.gov/search?q=C2746980408-LPCLOUD, and on Google Earth Engine (GEE) with asset ID: projects/glad/HLSDIST/current

The DIST-ALERT on GFW is a derivative of this, and additional data layers not used in the GFW product are available through the LPDAAC and GEE such as initial vegetation fraction, and disturbance duration. While the version on the LPDAAC is updated every 2-4 days, the data is updated weekly on GFW.  The product detects notable reductions in vegetation cover (measured as “vegetation fraction” or the percent of the ground that is covered by vegetation) for every pixel every time the new satellite data is acquired and the ground is not obscured by clouds or snow.

The current vegetation fraction estimate is compared to the minimum fraction for the same time period (within 15 days before and after) in the previous 3 years, and if there is a reduction, then the system identifies an alert in that pixel. Anomalies of at least a 10% reduction from the minimum become alerts in the original product, and on GFW, a higher threshold of 30% is used, to reduce noise, and false alerts in the dataset. Because the product compares each pixel to the minimum for the same time period in previous years, it takes into account regular seasonal variation in vegetation cover.   As the product is global and detects vegetation anomalies, much of the data may not be applicable to GFW users monitoring forests. Therefore, we mask the alerts with UMD’s tree cover map, allowing users to view only alerts within 30% canopy cover.""",
        title="Global all ecosystem disturbance alerts (DIST-ALERT)",
        license="CC-BY-SA-4.0",
        keywords=["vegetation", "disturbance", "alert", "wri"],
        providers=[
            Provider(
                name="World Resources Institute",
                roles=[ProviderRole.PRODUCER, ProviderRole.LICENSOR],
                url="https://github.com/wri/natural-lands-map/tree/main",
            )
        ],
        extent=collection_extent,
        extra_fields={
            "reference_date": "2015-01-01",
            "default_band": {
                "description": "(10000 * confidence) + (days since 2015)",
            },
            "intensity_band": {
                "description": "this is a hotspot layer where all alerts have value 255 and bilinear resampling on the overviews so that areas with dense alerts have higher values",
            },
            "version": "v001",
        },
    )


def main():
    items = create_dist_items()
    collection = create_collection()
    load_stac_data_to_db(collection, items)


if __name__ == "__main__":
    main()
