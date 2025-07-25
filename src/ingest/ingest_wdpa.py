from src.ingest.utils import (
    gdf_from_ndjson_chunked,
    ingest_to_postgis,
    create_index_if_not_exists,
)

WDPA_DATA_SOURCE = "s3://gfw-data-lake/wdpa_protected_areas/v202407/vector/epsg-4326/wdpa_protected_areas_v202407.ndjson"


def ingest_wdpa() -> None:
    """
    Main function to download WDPA data and ingest it to PostGIS in chunks.
    """
    print("Downloading and processing WDPA data in chunks...")

    for i, gdf_chunk in enumerate(gdf_from_ndjson_chunked(WDPA_DATA_SOURCE)):
        # Rename columns
        gdf_chunk = gdf_chunk.rename(columns={"id": "wdpa_id", "name": "wdpa_name"})

        # Add new name column
        gdf_chunk["name"] = gdf_chunk.apply(
            lambda row: ", ".join(
                filter(
                    None,
                    [
                        str(row.get("wdpa_name", "")),
                        str(row.get("desig", "")),
                        str(row.get("iso3", "")),
                    ],
                )
            ),
            axis=1,
        )

        # Add subtype column
        gdf_chunk["subtype"] = "protected-area"

        if_exists_param = "replace" if i == 0 else "append"
        ingest_to_postgis(
            table_name="geometries_wdpa", gdf=gdf_chunk, if_exists=if_exists_param
        )

    create_index_if_not_exists(
        table_name="geometries_wdpa",
        index_name="idx_geometries_wdpa_geom",
        column="geometry",
    )
    print("✓ WDPA ingestion completed successfully!")


if __name__ == "__main__":
    ingest_wdpa()
