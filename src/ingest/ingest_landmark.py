from src.ingest.utils import (
    create_geometry_index_if_not_exists,
    create_id_index_if_not_exists,
    create_text_search_index_if_not_exists,
    gdf_from_ndjson_chunked,
    ingest_to_postgis,
)
from src.utils.geocoding_helpers import SOURCE_ID_MAPPING

LANDMARK_DATA_SOURCE = "s3://gfw-data-lake/landmark_ip_lc_and_indicative_poly/v20250625/vector/epsg-4326/default.ndjson"


def ingest_landmark() -> None:
    """
    Main function to download Landmark data and ingest it to PostGIS in chunks.
    """
    print("Downloading and processing Landmark data in chunks...")

    for i, gdf_chunk in enumerate(
        gdf_from_ndjson_chunked(LANDMARK_DATA_SOURCE)
    ):
        # Rename columns
        gdf_chunk = gdf_chunk.rename(columns={"name": "landmark_name"})

        # Add new name column
        gdf_chunk["name"] = gdf_chunk.apply(
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
        gdf_chunk["subtype"] = "indigenous-and-community-land"

        if_exists_param = "replace" if i == 0 else "append"
        ingest_to_postgis(
            table_name="geometries_landmark",
            gdf=gdf_chunk,
            if_exists=if_exists_param,
        )

    create_geometry_index_if_not_exists(
        table_name="geometries_landmark",
        index_name="idx_geometries_landmark_geom",
        column="geometry",
    )
    create_text_search_index_if_not_exists(
        table_name="geometries_landmark",
        index_name="idx_geometries_landmark_name_gin",
        column="name",
    )
    id_column = SOURCE_ID_MAPPING["landmark"]["id_column"]
    create_id_index_if_not_exists(
        table_name="geometries_landmark",
        index_name=f"idx_geometries_landmark_{id_column}",
        column=id_column,
    )

    print("✓ Landmark ingestion completed successfully!")


if __name__ == "__main__":
    ingest_landmark()
