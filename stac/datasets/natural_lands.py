from datetime import datetime

import dotenv
from pystac import (
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

COLLECTION_ID = "natural-lands-map-v1-1"

CLASSIFICATION_VALUES = {
    2: "natural forests",
    3: "natural short vegetation",
    4: "natural water",
    5: "mangroves",
    6: "bare",
    7: "snow",
    8: "wet natural forests",
    9: "natural peat forests",
    10: "wet natural short vegetation",
    11: "natural peat short vegetation",
    12: "crop",
    13: "built",
    14: "non-natural tree cover",
    15: "non-natural short vegetation",
    16: "non-natural water",
    17: "wet non-natural tree cover",
    18: "non-natural peat tree cover",
    19: "wet non-natural short vegetation",
    20: "non-natural peat short vegetation",
    21: "non-natural bare",
}


def create_nl_items() -> list[Item]:
    url = "s3://lcl-cogs/natural-lands/natural-lands-map-v1-1.tif"
    nl_item = create_stac_item(
        source=url,
        id="natural-lands-map-v1-1",
        collection=COLLECTION_ID,
        with_raster=True,
        with_proj=True,
        properties={
            "start_datetime": str(datetime(2020, 1, 1)),
            "end_datetime": str(datetime(2020, 12, 31)),
        },
    )
    nl_item = convert_valid_percentage_to_int(nl_item)
    return [nl_item]


def create_collection() -> Collection:
    spatial_extent = SpatialExtent(bboxes=[[-180, -60, 180, 75]])
    temporal_extent = TemporalExtent(
        intervals=[[datetime(2020, 1, 1), datetime(2020, 12, 31)]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )

    metadata = get_metadata_from_yaml(
        "src/tools/analytics_datasets.yml", "Natural lands"
    )
    metadata["classification_values"] = CLASSIFICATION_VALUES

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
    items = create_nl_items()
    print(f"Loaded {len(items)} STAC items")
    collection = create_collection()
    print("Loading STAC data to database...")
    load_stac_data_to_db(collection, items, delete_existing_items=False)
    print("Done!")


if __name__ == "__main__":
    main()
