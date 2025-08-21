import re
from datetime import datetime

import boto3
import dotenv
from pystac import (
    Asset,
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

from stac.datasets.utils import (
    convert_valid_percentage_to_int,
    load_stac_data_to_db,
)

dotenv.load_dotenv("stac/env/.env_staging")

set_stac_version("1.1.0")

COLLECTION_ID = "dist-alerts"


def get_latest_version_from_s3() -> str:
    """
    Dynamically discover the latest version from S3 by listing objects and finding the most recent version.

    Returns:
        Latest version string (e.g., 'v20250816')
    """
    s3_client = boto3.client(
        "s3", config=boto3.session.Config(user_agent_extra="project-zeno")
    )

    print(
        "Searching for latest version in s3://gfw-data-lake/umd_glad_dist_alerts/"
    )

    # List objects with the prefix
    response = s3_client.list_objects_v2(
        Bucket="gfw-data-lake",
        Prefix="umd_glad_dist_alerts/",
        Delimiter="/",
        RequestPayer="requester",
    )

    # Extract version folders from common prefixes
    versions = []
    if "CommonPrefixes" in response:
        for prefix_obj in response["CommonPrefixes"]:
            prefix_path = prefix_obj["Prefix"]
            # Extract version from path like "umd_glad_dist_alerts/v20250816/"
            match = re.search(r"v(\d{8})/?$", prefix_path)
            if match:
                version = match.group(0).rstrip("/")
                versions.append(version)

    if not versions:
        print(
            "No versions found in CommonPrefixes, trying direct object listing..."
        )
        # Fallback: try listing objects directly if common prefixes don't work
        response = s3_client.list_objects_v2(
            Bucket="gfw-data-lake",
            Prefix="umd_glad_dist_alerts/",
            RequestPayer="requester",
        )

        for obj in response.get("Contents", []):
            key = obj["Key"]
            # Extract version from object keys like "umd_glad_dist_alerts/v20250816/raster/..."
            match = re.search(r"umd_glad_dist_alerts/(v\d{8})/", key)
            if match:
                version = match.group(1)
                if version not in versions:
                    versions.append(version)

    if not versions:
        raise ValueError(
            "No versions found in S3 bucket gfw-data-lake with prefix umd_glad_dist_alerts/"
        )

    # Sort versions and return the latest (highest date)
    versions.sort(reverse=True)
    latest_version = versions[0]

    print(f"Using latest version: {latest_version}")
    return latest_version


def create_dist_items() -> list[Item]:
    # Dynamically get the latest version
    latest_version = get_latest_version_from_s3()

    # Extract date from version tag (e.g., 'v20250222' -> '2025-02-22')
    version_date_str = latest_version[1:]  # Remove 'v' prefix
    end_date = datetime.strptime(version_date_str, "%Y%m%d")

    # Create base item with default asset
    url = f"s3://gfw-data-lake/umd_glad_dist_alerts/{latest_version}/raster/epsg-4326/cog/default.tif"
    item = create_stac_item(
        source=url,
        id="dist-alerts",
        collection=COLLECTION_ID,
        with_raster=True,
        with_proj=True,
        properties={
            "start_datetime": str(datetime(2015, 1, 1)),
            "end_datetime": str(end_date),
        },
        asset_name="default",
    )

    item = convert_valid_percentage_to_int(item, asset_name="default")

    # Add intensity asset to the same item
    intensity_url = f"s3://gfw-data-lake/umd_glad_dist_alerts/{latest_version}/raster/epsg-4326/cog/intensity.tif"
    item.add_asset(
        "intensity",
        Asset(
            href=intensity_url,
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            title="Intensity Band",
            description="Hotspot layer where all alerts have value 255 and bilinear resampling on the overviews so that areas with dense alerts have higher values",
            roles=["data"],
        ),
    )

    return [item]


def create_collection() -> Collection:
    # Get the latest version to determine the end date
    latest_version = get_latest_version_from_s3()
    version_date_str = latest_version[1:]  # Remove 'v' prefix
    end_date = datetime.strptime(version_date_str, "%Y%m%d")

    spatial_extent = SpatialExtent(bboxes=[[-180, -60, 180, 75]])
    temporal_extent = TemporalExtent(
        intervals=[[datetime(2015, 1, 1), end_date]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )

    return Collection(
        id=COLLECTION_ID,
        description="""
            This dataset is a derivative of the OPERA's DIST-ALERT product (OPERA Land Surface
            Disturbance Alert from Harmonized Landsat Sentinel-2 product), which is derived through
            a time-series analysis of harmonized data from the NASA/USGS Landsat and ESA Sentinel-2
            satellites (known as the HLS dataset). The product identifies and continuously monitors
            vegetation cover change in 30-m pixels across the globe. It can be accessed through the
            LPDAAC website here: https://search.earthdata.nasa.gov/search?q=C2746980408-LPCLOUD,
            and on Google Earth Engine (GEE) with asset ID: projects/glad/HLSDIST/current

            The DIST-ALERT on GFW is a derivative of this, and additional data layers not used in
            the GFW product are available through the LPDAAC and GEE such as initial vegetation
            fraction, and disturbance duration. While the version on the LPDAAC is updated every
            2-4 days, the data is updated weekly on GFW. The product detects notable reductions in
            vegetation cover (measured as "vegetation fraction" or the percent of the ground that is
            covered by vegetation) for every pixel every time the new satellite data is acquired and
            the ground is not obscured by clouds or snow.

            The current vegetation fraction estimate is compared to the minimum fraction for the same
            time period (within 15 days before and after) in the previous 3 years, and if there is a
            reduction, then the system identifies an alert in that pixel. Anomalies of at least a 10%
            reduction from the minimum become alerts in the original product, and on GFW, a higher
            threshold of 30% is used, to reduce noise, and false alerts in the dataset. Because the
            product compares each pixel to the minimum for the same time period in previous years, it
            takes into account regular seasonal variation in vegetation cover. As the product is global
            and detects vegetation anomalies, much of the data may not be applicable to GFW users
            monitoring forests. Therefore, we mask the alerts with UMD's tree cover map, allowing users
            to view only alerts within 30% canopy cover.
        """,
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
    load_stac_data_to_db(collection, items, delete_existing_items=True)


if __name__ == "__main__":
    main()
