from src.ingest.utils import (
    gdf_from_ndjson_chunked,
    ingest_to_postgis,
    create_index_if_not_exists,
)

KBA_DATA_SOURCE = "s3://gfw-data-lake/birdlife_key_biodiversity_areas/v202106/vector/epsg-4326/birdlife_key_biodiversity_areas_v202106.ndjson"


def ingest_kba() -> None:
    """
    Main function to download KBA data and ingest it to PostGIS in chunks.
    """
    print("Downloading and processing KBA data in chunks...")

    for i, gdf_chunk in enumerate(gdf_from_ndjson_chunked(KBA_DATA_SOURCE)):
        # add a name column that does UPDATE kba SET name = concat_ws(', ', natname, intname, iso3);
        gdf_chunk["name"] = gdf_chunk.apply(
            lambda row: ", ".join(
                filter(None, [row.get("natname"), row.get("intname"), row.get("iso3")])
            ),
            axis=1,
        )

        if_exists_param = "replace" if i == 0 else "append"
        ingest_to_postgis(
            table_name="geometries_kba", gdf=gdf_chunk, if_exists=if_exists_param
        )

    create_index_if_not_exists(
        table_name="geometries_kba",
        index_name="idx_geometries_kba_geom",
        column="geometry",
    )
    print("✓ KBA ingestion completed successfully!")


if __name__ == "__main__":
    ingest_kba()
