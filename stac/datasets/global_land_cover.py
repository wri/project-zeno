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

COLLECTION_ID = "global-land-cover-v-2"

# Default classification values - can be overridden by YAML injection
DEFAULT_CLASSIFICATION_VALUES = {
    0: "Bare ground & sparse vegetation",
    1: "Short vegetation",
    2: "Tree cover",
    3: "Wetland - short vegetation",
    4: "Water",
    5: "Snow/ice",
    6: "Cropland",
    7: "Built-up",
    8: "Cultivated grasslands",
}

DEFAULT_CLASSIFICATION_DESCRIPTIONS = {
    0: "Land with 0-19% vegetation fraction.",
    1: "Non-treed vegetation cover with 20% or more vegetation fraction.",
    2: (
        "Forest is an area with tree height ≥5 m at the Landsat pixel scale. "
        "Our definition includes wildland, managed, and planted forests, "
        "agroforestry, orchards, and natural tree regrowth."
    ),
    3: (
        "Non-treed vegetation cover with 20% or more vegetation fraction that "
        "are transitional between terrestrial and aquatic systems where the "
        "water table is usually at or near the surface or the land is covered "
        "by shallow water."
    ),
    4: (
        "Open surface water, or simply water, is defined as inland water that "
        "covers ≥50% of a pixel for 20% or more of the year and is not "
        "obscured by objects above the surface (e.g., tree canopy, floating "
        "aquatic vegetation, bridges, or ice)."
    ),
    5: "Includes land covered by glaciers and snow which remains during the entire year.",
    6: (
        "Land used to produce annual and perennial herbaceous crops for human "
        "consumption, forage, and biofuel. Our definition excludes tree crops, "
        "permanent pastures, and shifting cultivation."
    ),
    7: (
        "Consists of man-made land surfaces associated with infrastructure, "
        "commercial and residential land uses. At the Landsat spatial resolution, "
        "we define the built-up land class as pixels that include man-made surfaces, "
        "even if such surfaces do not dominate within the pixel."
    ),
    8: (
        "Cultivated grassland includes areas where grasses and other forage plants "
        "have been intentionally planted and managed, as well as areas of native "
        "grassland-type vegetation where they clearly exhibit active and 'heavy' "
        "management for specific human-directed uses, such as directed grazing "
        "of livestock."
    ),
}

# Global land cover files from S3 bucket
GLOBAL_LAND_COVER_FILES = [
    ("global_land_cover_2015.tif", 2015),
    ("global_land_cover_2016.tif", 2016),
    ("global_land_cover_2017.tif", 2017),
    ("global_land_cover_2018.tif", 2018),
    ("global_land_cover_2019.tif", 2019),
    ("global_land_cover_2020.tif", 2020),
    ("global_land_cover_2021.tif", 2021),
    ("global_land_cover_2022.tif", 2022),
    ("global_land_cover_2023.tif", 2023),
    ("global_land_cover_2024.tif", 2024),
]


def create_global_land_cover_items() -> list[Item]:
    """Create STAC items for all global land cover files."""
    items = []

    for filename, year in GLOBAL_LAND_COVER_FILES:
        url = f"s3://lcl-cogs/global-land-cover/{filename}"
        item_id = f"global-land-cover-{year}"
        print(f"Creating item for {item_id}")

        # Create STAC item
        item = create_stac_item(
            source=url,
            id=item_id,
            collection=COLLECTION_ID,
            with_raster=True,
            with_proj=True,
            properties={
                "start_datetime": str(datetime(year, 1, 1)),
                "end_datetime": str(datetime(year, 12, 31)),
                "year": year,
                "title": f"Global Land Cover {year}",
                "description": f"Global land cover classification for {year}",
            },
        )

        # Convert valid percentage to int if needed
        item = convert_valid_percentage_to_int(item)
        items.append(item)

    return items


def create_collection() -> Collection:
    """Create the global land cover collection."""
    spatial_extent = SpatialExtent(bboxes=[[-180, -90, 180, 90]])
    temporal_extent = TemporalExtent(
        intervals=[[datetime(2015, 1, 1), datetime(2024, 12, 31)]]
    )
    collection_extent = Extent(
        spatial=spatial_extent, temporal=temporal_extent
    )
    metadata = get_metadata_from_yaml("Global land cover")
    metadata["classification_values"] = DEFAULT_CLASSIFICATION_VALUES
    metadata["classification_descriptions"] = (
        DEFAULT_CLASSIFICATION_DESCRIPTIONS
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
    """Main function to create and load STAC items."""
    print("Creating collection...")
    collection = create_collection()
    print("Creating items...")
    items = create_global_land_cover_items()
    print(f"Created {len(items)} STAC items for global land cover data")
    print("Loading STAC data to database...")
    load_stac_data_to_db(collection, items, delete_existing_items=False)
    print("Done!")


if __name__ == "__main__":
    main()
