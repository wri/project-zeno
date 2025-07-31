from src.ingest.utils import (
    gdf_from_ndjson_chunked,
    ingest_to_postgis,
    create_geometry_index_if_not_exists,
    create_text_search_index_if_not_exists,
    create_id_index_if_not_exists,
)
from src.utils.geocoding_helpers import SOURCE_ID_MAPPING

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

    create_geometry_index_if_not_exists(
        table_name="geometries_wdpa",
        index_name="idx_geometries_wdpa_geom",
        column="geometry",
    )
    create_text_search_index_if_not_exists(
        table_name="geometries_wdpa",
        index_name="idx_geometries_wdpa_name_gin",
        column="name"
    )
    id_column = SOURCE_ID_MAPPING["wdpa"]["id_column"]
    create_id_index_if_not_exists(
        table_name="geometries_wdpa",
        index_name=f"idx_geometries_wdpa_{id_column}",
        column=id_column
    )
    print("✓ WDPA ingestion completed successfully!")


if __name__ == "__main__":
    ingest_wdpa()
