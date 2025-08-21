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

COLLECTION_ID = "umd-tree-cover-loss"


def create_dist_items() -> list[Item]:
    url = "s3://gfw-data-lake/umd_tree_cover_loss/v1.12/raster/epsg-4326/cog/default.tif"
    tcl_item = create_stac_item(
        source=url,
        id="umd-tree-cover-loss-intensity",
        collection=COLLECTION_ID,
        with_raster=True,
        with_proj=True,
        properties={
            "start_datetime": str(datetime(2000, 1, 1)),
            "end_datetime": str(datetime(2024, 12, 31)),
        },
    )
    tcl_item = convert_valid_percentage_to_int(tcl_item)

    return [tcl_item]


def create_collection() -> Collection:
    spatial_extent = SpatialExtent(bboxes=[[-180, -60, 180, 75]])
    temporal_extent = TemporalExtent(
        intervals=[[datetime(2000, 1, 1), datetime(2024, 12, 31)]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )
    metadata = get_metadata_from_yaml(
        "src/tools/analytics_datasets.yml", "Tree cover loss"
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
    load_stac_data_to_db(collection, items)


if __name__ == "__main__":
    main()
