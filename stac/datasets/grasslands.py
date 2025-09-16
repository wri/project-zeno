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

COLLECTION_ID = "grasslands-v-1"

CLASSIFICATION_VALUES = {
    0: "Other",
    1: "Cultivated grassland",
    2: "Natural/semi-natural grassland",
    3: "Open Shrubland",
}


def create_grasslands_items() -> Item:
    items = []
    for year in range(2000, 2023):
        print(f"Creating item for {year}")
        url = f"s3://gfw-data-lake/gfw_grasslands/v1/geotiff/grasslands_{year}.tif"
        item = create_stac_item(
            source=url,
            id=f"grasslands-{year}",
            collection=COLLECTION_ID,
            with_raster=True,
            with_proj=True,
            properties={
                "start_datetime": f"{year}-01-01",
                "end_datetime": f"{year}-12-31",
            },
        )
        item = convert_valid_percentage_to_int(item)
        items.append(item)
    return items


def create_collection() -> Collection:
    spatial_extent = SpatialExtent(bboxes=[[-180, -60, 180, 75]])
    temporal_extent = TemporalExtent(
        intervals=[[datetime(2024, 1, 1), datetime(2024, 12, 31)]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )

    metadata = get_metadata_from_yaml(
        "Global natural/semi-natural grassland extent"
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
    items = create_grasslands_items()
    print(f"Loaded {len(items)} STAC items")
    collection = create_collection()
    print("Loading STAC data to database...")
    load_stac_data_to_db(collection, items, delete_existing_items=True)
    print("Done!")


if __name__ == "__main__":
    main()
