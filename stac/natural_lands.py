import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from multiprocessing import cpu_count

import dotenv
from google.cloud import storage
from pypgstac.db import PgstacDB
from pypgstac.load import Loader, Methods
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

dotenv.load_dotenv()

set_stac_version("1.1.0")

GC_BUCKET = "lcl_public"
GC_FOLDER = "SBTN_NaturalLands/v1_1/classification"

COLLECTION_ID = "NaturalLands"

# SBTN Natural Lands classification values
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


def get_loader():
    required_env_vars = [
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
    ]

    missing_vars = [var for var in required_env_vars if var not in os.environ]

    if missing_vars:
        raise EnvironmentError(
            f"Missing required environment variables for pgstac connection: {', '.join(missing_vars)}"
        )

    print(
        "All required environment variables for pgstac database connection are set."
    )

    db = PgstacDB()
    loader = Loader(db=db)

    return loader


def get_tif_urls() -> list[str]:
    client = storage.Client()
    bucket = client.bucket(GC_BUCKET)
    blobs = bucket.list_blobs(prefix=GC_FOLDER)

    tif_urls = []
    for blob in blobs:
        if blob.name.endswith(".tif"):
            url = f"https://storage.googleapis.com/{GC_BUCKET}/{blob.name}"
            tif_urls.append(url)

    print(f"Found {len(tif_urls)} TIF files")

    return tif_urls


def create_stac_item_with_extensions(url: str) -> Item:
    return create_stac_item(
        url,
        extensions=[
            "https://stac-extensions.github.io/projection/v2.0.0/schema.json",
            "https://stac-extensions.github.io/raster/v2.0.0/schema.json",
        ],
        properties={
            "start_datetime": datetime(2020, 1, 1),
            "end_datetime": datetime(2020, 12, 31),
        },
    )


def get_stac_items() -> list[Item]:
    with ThreadPoolExecutor(max_workers=cpu_count()) as executor:
        items = list(
            executor.map(
                create_stac_item_with_extensions, get_tif_urls()[:3]
            )  # TODO: Remove the limit
        )

    return items


def create_collection() -> Collection:
    spatial_extent = SpatialExtent(bboxes=[[-180, -60, 180, 75]])
    temporal_extent = TemporalExtent(
        intervals=[[datetime(2020, 1, 1), datetime(2020, 12, 31)]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )

    collection = Collection(
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
    )

    # Add SBTN Natural Lands specific metadata to collection
    collection.extra_fields.update(
        {
            "classification_values": CLASSIFICATION_VALUES,
            "classification_band": {
                "description": "Land cover classification",
                "min": 2,
                "max": 21,
            },
        }
    )

    return collection


def load_stac_data_to_db(collection: Collection, items: list[Item]):
    loader = get_loader()

    loader.load_collections(
        io.BytesIO(json.dumps(collection.to_dict()).encode("utf-8")),
        insert_mode=Methods.upsert,
    )

    for item in items:
        item.clear_links()

    loader.load_items(
        (item.to_dict() for item in items),
        insert_mode=Methods.upsert,
    )


def main():
    items = get_stac_items()
    collection = create_collection()

    for item in items:
        collection.add_item(item)

    # collection.save("stac/natural_lands_collection.json")
    # print(collection.to_dict())

    load_stac_data_to_db(collection, items)


if __name__ == "__main__":
    main()

# For loading the STAC records into a database
# https://github.com/developmentseed/eoapi-foss4gna/blob/main/scripts/load-stac-records
