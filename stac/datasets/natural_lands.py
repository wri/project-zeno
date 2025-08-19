from datetime import datetime

import dotenv
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

from stac.datasets.utils import load_stac_data_to_db

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
    valid_percent = (
        nl_item.assets["asset"]
        .extra_fields["raster:bands"][0]["statistics"]["valid_percent"]
        .item()
    )
    nl_item.assets["asset"].extra_fields["raster:bands"][0]["statistics"][
        "valid_percent"
    ] = valid_percent
    return [nl_item]


def create_collection() -> Collection:
    spatial_extent = SpatialExtent(bboxes=[[-180, -60, 180, 75]])
    temporal_extent = TemporalExtent(
        intervals=[[datetime(2020, 1, 1), datetime(2020, 12, 31)]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )

    return Collection(
        id=COLLECTION_ID,
        description="""The SBTN Natural Lands Map v1.1 is a 2020 baseline map of
        natural and non-natural land covers intended for use by companies setting
        science-based targets for nature, specifically the SBTN Land target #1:
        no conversion of natural ecosystems.""",
        title="SBTN Natural Lands Map v1.1",
        license="CC-BY-SA-4.0",
        keywords=["ecosystems", "landcover", "landuse-landcover", "wri"],
        providers=[
            Provider(
                name="World Resources Institute",
                roles=[ProviderRole.PRODUCER, ProviderRole.LICENSOR],
                url="https://github.com/wri/natural-lands-map/tree/main",
            )
        ],
        extent=collection_extent,
        extra_fields={
            "classification_values": CLASSIFICATION_VALUES,
            "classification_band": {
                "description": "Land cover classification",
                "min": 2,
                "max": 21,
            },
            "version": "1.1",
        },
    )


def main():
    items = create_nl_items()
    print(f"Loaded {len(items)} STAC items")
    collection = create_collection()
    print("Loading STAC data to database...")
    load_stac_data_to_db(collection, items, delete_existing_items=True)
    print("Done!")


if __name__ == "__main__":
    main()
