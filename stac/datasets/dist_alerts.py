import re
from datetime import datetime

import boto3
import dotenv
from pystac import (
    Asset,
    Collection,
    Extent,
    Item,
    SpatialExtent,
    TemporalExtent,
    set_stac_version,
)
from rio_stac import create_stac_item

from stac.datasets.utils import (
    convert_valid_percentage_to_int,
    get_metadata_from_yaml,
    load_stac_data_to_db,
)

dotenv.load_dotenv("stac/env/.env_staging")

set_stac_version("1.1.0")

COLLECTION_ID = "dist-alerts-v1"


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
            "start_datetime": str(datetime(2023, 1, 1)),
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
        intervals=[[datetime(2023, 1, 1), end_date]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )

    metadata = get_metadata_from_yaml(
        "Global all ecosystem disturbance alerts (DIST-ALERT)"
    )

    return Collection(
        id=COLLECTION_ID,
        description=metadata.pop("description"),
        title=metadata.pop("dataset_name"),
        license=metadata.pop("license"),
        keywords=metadata.pop("keywords"),
        extent=collection_extent,
        extra_fields=metadata,
    )


def main():
    items = create_dist_items()
    collection = create_collection()
    load_stac_data_to_db(collection, items, delete_existing_items=False)


if __name__ == "__main__":
    main()
