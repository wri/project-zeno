from src.ingest.utils import (
    create_geometry_index_if_not_exists,
    create_id_index_if_not_exists,
    create_text_search_index_if_not_exists,
    gdf_from_ndjson_chunked,
    ingest_to_postgis,
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
        gdf_chunk = gdf_chunk.rename(
            columns={"id": "wdpa_id", "name": "wdpa_name"}
        )

        # Simplify geometries with adaptive tolerance based on area
        def simplify_geometry(geom):
            if geom is None or geom.is_empty:
                return geom

            # Calculate area in square degrees (approximate)
            area = geom.area

            # Adaptive tolerance: larger geometries get more aggressive simplification
            # Small geometries (< 0.01 sq degrees): tolerance = 0.001 (~111m at equator)
            # Medium geometries (0.01-1 sq degrees): tolerance = 0.005 (~555m at equator)
            # Large geometries (> 1 sq degrees): tolerance = 0.01 (~1.1km at equator)
            if area < 0.01:
                tolerance = 0.001
            elif area < 1.0:
                tolerance = 0.005
            else:
                tolerance = 0.01

            try:
                simplified = geom.simplify(tolerance, preserve_topology=True)
                return simplified if simplified.is_valid else geom
            except Exception:
                return geom

        gdf_chunk["geometry"] = gdf_chunk["geometry"].apply(simplify_geometry)

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
            table_name="geometries_wdpa",
            gdf=gdf_chunk,
            if_exists=if_exists_param,
        )

    create_geometry_index_if_not_exists(
        table_name="geometries_wdpa",
        index_name="idx_geometries_wdpa_geom",
        column="geometry",
    )
    create_text_search_index_if_not_exists(
        table_name="geometries_wdpa",
        index_name="idx_geometries_wdpa_name_gin",
        column="name",
    )
    id_column = SOURCE_ID_MAPPING["wdpa"]["id_column"]
    create_id_index_if_not_exists(
        table_name="geometries_wdpa",
        index_name=f"idx_geometries_wdpa_{id_column}",
        column=id_column,
    )
    print("✓ WDPA ingestion completed successfully!")


if __name__ == "__main__":
    ingest_wdpa()
