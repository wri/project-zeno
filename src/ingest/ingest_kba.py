from src.ingest.utils import gdf_from_ndjson, ingest_to_postgis

KBA_DATA_SOURCE = "s3://gfw-data-lake/birdlife_key_biodiversity_areas/v202106/vector/epsg-4326/birdlife_key_biodiversity_areas_v202106.ndjson"


def ingest_kba() -> None:
    """
    Main function to download KBA data and ingest it to PostGIS.
    """
    print("Downloading KBA data...")
    gdf = gdf_from_ndjson(KBA_DATA_SOURCE)

    # add a name column that does UPDATE kba SET name = concat_ws(', ', natname, intname, iso3);
    gdf["name"] = gdf.apply(
        lambda row: ", ".join(
            filter(None, [row.get("natname"), row.get("intname"), row.get("iso3")])
        ),
        axis=1,
    )

    print("Ingesting KBA data to PostGIS...")
    ingest_to_postgis(table_name="geometries_kba", gdf=gdf)

    print("✓ KBA ingestion completed successfully!")


if __name__ == "__main__":
    ingest_kba()
