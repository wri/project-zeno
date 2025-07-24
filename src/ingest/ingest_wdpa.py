from src.ingest.utils import gdf_from_ndjson, ingest_to_postgis

WDPA_DATA_SOURCE = "s3://gfw-data-lake/wdpa_protected_areas/v202407/vector/epsg-4326/wdpa_protected_areas_v202407.ndjson"


def ingest_wdpa() -> None:
    """
    Main function to download WDPA data and ingest it to PostGIS.
    """
    print("Downloading WDPA data...")
    gdf = gdf_from_ndjson(WDPA_DATA_SOURCE)

    # Rename columns
    gdf = gdf.rename(columns={"id": "wdpa_id", "name": "wdpa_name"})

    # Add new name column
    gdf["name"] = gdf.apply(
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
    gdf["subtype"] = "protected-area"

    print("Ingesting WDPA data to PostGIS...")
    ingest_to_postgis(table_name="geometries_wdpa", gdf=gdf)

    print("WDPA ingestion completed successfully!")


if __name__ == "__main__":
    ingest_wdpa()
