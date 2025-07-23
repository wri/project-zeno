#!/usr/bin/env python3
"""
export_optimized_parquets.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Export optimized parquet files with separated geometry storage:
- Main tables without geometry (smaller, faster for search)
- Separate geometry table for when geometry is needed

This script should be run after create_gadm_plus.sql to export
the optimized table structure to parquet files.
"""

import argparse
from pathlib import Path

import duckdb

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def export_tables_to_parquet(db_path: str, output_dir: str):
    """Export optimized tables to parquet files"""
    db_path = Path(db_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Connecting to database: {db_path}")
    conn = duckdb.connect(str(db_path))

    # Load spatial extension
    conn.execute("INSTALL spatial;")
    conn.execute("LOAD spatial;")

    # Export main tables without geometry
    tables_to_export = {
        "gadm": "gadm_no_geom.parquet",
        "kba": "kba_no_geom.parquet",
        "landmark": "landmark_no_geom.parquet",
        "wdpa": "wdpa_no_geom.parquet",
        "gadm_plus": "gadm_plus.parquet",  # Unified search table (replaces gadm_plus_search)
    }

    for table, filename in tables_to_export.items():
        output_path = output_dir / filename
        logger.info(f"Exporting {table} to {output_path}")

        try:
            # For main tables, exclude geometry if it exists
            if table in ["gadm", "kba", "landmark", "wdpa"]:
                # Check if geometry column exists
                columns_query = f"DESCRIBE {table}"
                columns_df = conn.sql(columns_query).df()
                has_geometry = "geometry" in columns_df["column_name"].values

                if has_geometry:
                    export_query = f"SELECT * EXCLUDE geometry FROM {table}"
                else:
                    export_query = f"SELECT * FROM {table}"
            else:
                export_query = f"SELECT * FROM {table}"

            conn.sql(
                f"COPY ({export_query}) TO '{output_path}' (FORMAT PARQUET)"
            )
            logger.info(f"✓ Exported {table}")

        except Exception as e:
            logger.warning(f"Failed to export {table}: {e}")

    # Export geometry table
    geometry_path = output_dir / "geometries.parquet"
    logger.info(f"Exporting geometries to {geometry_path}")

    try:
        conn.sql(
            f"COPY (SELECT * FROM geometries) TO '{geometry_path}' (FORMAT PARQUET)"
        )
        logger.info("✓ Exported geometries table")
    except Exception as e:
        logger.error(f"Failed to export geometries: {e}")

    # Show file sizes for comparison
    logger.info("\n=== File Size Summary ===")
    for file in output_dir.glob("*.parquet"):
        size_mb = file.stat().st_size / (1024 * 1024)
        logger.info(f"{file.name}: {size_mb:.2f} MB")

    conn.close()
    logger.info("Export completed successfully!")


def main():
    parser = argparse.ArgumentParser(
        description="Export optimized parquet files"
    )
    parser.add_argument(
        "--db-path",
        default="data/geocode/basemaps.duckdb",
        help="Path to DuckDB database",
    )
    parser.add_argument(
        "--output-dir",
        default="data/geocode/exports",
        help="Output directory for parquet files",
    )

    args = parser.parse_args()
    export_tables_to_parquet(args.db_path, args.output_dir)


if __name__ == "__main__":
    main()
