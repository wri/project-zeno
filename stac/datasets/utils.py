import io
import json
import os
from typing import Any, Dict

import yaml
from pypgstac.db import PgstacDB
from pypgstac.load import Loader, Methods
from pystac import Collection, Item


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


def delete_collection_items(collection_id: str):
    """Delete all items from a collection."""
    db = PgstacDB()
    print(f"Deleting all items from collection '{collection_id}'")
    try:
        db.query_one(
            "DELETE FROM pgstac.items WHERE collection = %s", (collection_id,)
        )
    except Exception as e:
        print(f"Error deleting items for collection '{collection_id}': {e}")
    print(f"Successfully deleted items for collection '{collection_id}'")


def load_stac_data_to_db(
    collection: Collection,
    items: list[Item],
    delete_existing_items: bool = False,
):
    """
    Load STAC data to database.

    Args:
        collection: The STAC collection to load
        items: List of STAC items to load
        delete_existing: If True, delete existing items before loading new ones
    """
    loader = get_loader()

    # Delete existing items if requested
    if delete_existing_items:
        delete_collection_items(collection.id)

    print("Loading collection to database")
    loader.load_collections(
        io.BytesIO(json.dumps(collection.to_dict()).encode("utf-8")),
        insert_mode=Methods.upsert,
    )

    for item in items:
        item.clear_links()

    print(f"Loading {len(items)} items to database")
    loader.load_items(
        (item.to_dict() for item in items),
        insert_mode=Methods.upsert,
    )


def convert_valid_percentage_to_int(
    item: Item, asset_name: str = "asset"
) -> Item:
    """
    Convert valid percentage from numpy to python float.
    """
    valid_percent = (
        item.assets[asset_name]
        .extra_fields["raster:bands"][0]["statistics"]["valid_percent"]
        .item()
    )
    item.assets[asset_name].extra_fields["raster:bands"][0]["statistics"][
        "valid_percent"
    ] = valid_percent

    return item


def get_metadata_from_yaml(
    yaml_file_path: str, dataset_key: str
) -> Dict[str, Any]:
    """
    Get metadata from yaml file for a specific dataset key.

    Args:
        yaml_file_path: Path to the analytics_datasets.yml file
        dataset_key: The dataset key to extract (e.g., "Global land cover")

    Returns:
        Dictionary containing the metadata for the STAC collection
    """
    with open(yaml_file_path, "r") as f:
        data = yaml.safe_load(f)

    # Find the dataset by name
    dataset = None
    for d in data.get("datasets", []):
        if d.get("dataset_name") == dataset_key:
            dataset = d
            break

    if not dataset:
        print(
            f"Warning: Dataset '{dataset_key}' not found in {yaml_file_path}"
        )
        return {}

    # Create extra fields from the dataset information
    metadata = {"dataset_name": dataset_key}

    # Add fields from the YAML dataset
    if dataset.get("license"):
        metadata["license"] = dataset["license"]

    if dataset.get("geographic_coverage"):
        metadata["geographic_coverage"] = dataset["geographic_coverage"]

    if dataset.get("resolution"):
        metadata["spatial_resolution"] = dataset["resolution"]

    if dataset.get("update_frequency"):
        metadata["update_frequency"] = dataset["update_frequency"]

    if dataset.get("content_date"):
        metadata["content_date"] = dataset["content_date"]

    if dataset.get("keywords"):
        metadata["keywords"] = dataset["keywords"]

    if dataset.get("description"):
        metadata["description"] = dataset["description"]

    if dataset.get("methodology"):
        metadata["methodology"] = dataset["methodology"]

    if dataset.get("cautions"):
        metadata["cautions"] = dataset["cautions"]

    print(f"Metadata created from dataset '{dataset_key}' in {yaml_file_path}")
    return metadata
