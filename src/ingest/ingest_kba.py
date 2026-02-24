from src.ingest.utils import (
    create_geometry_index_if_not_exists,
    create_id_index_if_not_exists,
    create_text_search_index_if_not_exists,
    gdf_from_ndjson_chunked,
    ingest_to_postgis,
)
from src.shared.geocoding_helpers import SOURCE_ID_MAPPING

KBA_DATA_SOURCE = "s3://ndjson-layers/KBAsGlobal_2024_September_03_POL.ndjson"


def ingest_kba() -> None:
    """
    Main function to download KBA data and ingest it to PostGIS in chunks.
    """
    print("Downloading and processing KBA data in chunks...")

    for i, gdf_chunk in enumerate(gdf_from_ndjson_chunked(KBA_DATA_SOURCE)):
        # Rename columns
        gdf_chunk = gdf_chunk.rename(columns={"SitRecID": "sitrecid"})
        gdf_chunk["name"] = gdf_chunk.apply(
            lambda row: ", ".join(
                filter(
                    None,
                    [row.get("NatName"), row.get("IntName"), row.get("ISO3")],
                )
            ),
            axis=1,
        )

        # Add subtype column
        gdf_chunk["subtype"] = "key-biodiversity-area"

        if_exists_param = "replace" if i == 0 else "append"
        ingest_to_postgis(
            table_name="geometries_kba",
            gdf=gdf_chunk,
            if_exists=if_exists_param,
        )

    create_geometry_index_if_not_exists(
        table_name="geometries_kba",
        index_name="idx_geometries_kba_geom",
        column="geometry",
    )
    create_text_search_index_if_not_exists(
        table_name="geometries_kba",
        index_name="idx_geometries_kba_name_gin",
        column="name",
    )
    id_column = SOURCE_ID_MAPPING["kba"]["id_column"]
    create_id_index_if_not_exists(
        table_name="geometries_kba",
        index_name=f"idx_geometries_kba_{id_column}",
        column=id_column,
    )
    create_id_index_if_not_exists(
        table_name="geometries_kba",
        index_name="idx_geometries_kba_sitrecid_text",
        column="(sitrecid::text)",
    )

    print("✓ KBA ingestion completed successfully!")


if __name__ == "__main__":
    ingest_kba()
