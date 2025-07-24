from src.ingest.utils import gdf_from_ndjson, ingest_to_postgis

LANDMARK_DATA_SOURCE = "s3://gfw-data-lake/landmark_indigenous_and_community_lands/v202411/vector/epsg-4326/default.ndjson"


def ingest_landmark() -> None:
    """
    Main function to download Landmark data and ingest it to PostGIS.
    """
    print("Downloading Landmark data...")
    gdf = gdf_from_ndjson(LANDMARK_DATA_SOURCE)

    # Rename columns
    gdf = gdf.rename(columns={"id": "landmark_id", "name": "landmark_name"})

    # Add new name column
    gdf["name"] = gdf.apply(
        lambda row: ", ".join(
            filter(
                None,
                [
                    str(row.get("landmark_name", "")),
                    str(row.get("category", "")),
                    str(row.get("iso_code", "")),
                ],
            )
        ),
        axis=1,
    )

    # Add subtype column
    gdf["subtype"] = "indigenous-and-community-land"

    print("Ingesting Landmark data to PostGIS...")
    ingest_to_postgis(table_name="geometries_landmark", gdf=gdf)

    print("✓ Landmark ingestion completed successfully!")


if __name__ == "__main__":
    ingest_landmark()
