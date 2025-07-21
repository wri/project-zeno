import os
import time
from functools import lru_cache

import duckdb
from dotenv import load_dotenv

from src.utils.logging_config import get_logger

load_dotenv()
logger = get_logger(__name__)

GADM_PLUS_TABLE = "data/geocode/exports/gadm_plus.parquet"

# Pre-loading tables is an option
# GADM_TABLE = "data/geocode/exports/gadm_no_geom.parquet"
# KBA_TABLE = "data/geocode/exports/kba_no_geom.parquet"
# LANDMARK_TABLE = "data/geocode/exports/landmark_no_geom.parquet"
# WDPA_TABLE = "data/geocode/exports/wdpa_no_geom.parquet"
# GEOMETRIES_TABLE = "data/geocode/exports/geometries.parquet"

@lru_cache(maxsize=1)
def get_db_connection(local_path: str = "local_basemaps.duckdb"):
    """Create and configure a DuckDB connection with necessary extensions."""
    start_time = time.time()
    conn = duckdb.connect(local_path)
    conn.sql("INSTALL spatial; LOAD spatial;")
    conn.sql("INSTALL httpfs; LOAD httpfs;")

    logger.debug(
        f"DuckDB connection created and extensions installed in {time.time() - start_time:.2f} seconds."
    )

    # Setup S3 access
    start_time = time.time()
    conn.execute(
        f"SET s3_region='{os.getenv('AWS_DEFAULT_REGION', 'us-east-1')}';"
    )
    conn.execute(f"SET s3_access_key_id='{os.getenv('AWS_ACCESS_KEY_ID')}';")
    conn.execute(
        f"SET s3_secret_access_key='{os.getenv('AWS_SECRET_ACCESS_KEY')}';"
    )

    logger.debug(f"S3 access setup in {time.time() - start_time:.2f} seconds.")

    # Load tables
    start_time = time.time()
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS gadm_plus AS SELECT * FROM '{GADM_PLUS_TABLE}';"
    )
    # conn.execute(f"CREATE TABLE IF NOT EXISTS gadm AS SELECT * FROM '{GADM_TABLE}';")
    # conn.execute(f"CREATE TABLE IF NOT EXISTS kba AS SELECT * FROM '{KBA_TABLE}';")
    # conn.execute(f"CREATE TABLE IF NOT EXISTS landmark AS SELECT * FROM '{LANDMARK_TABLE}';")
    # conn.execute(f"CREATE TABLE IF NOT EXISTS wdpa AS SELECT * FROM '{WDPA_TABLE}';")
    # conn.execute(
    #     f"CREATE TABLE IF NOT EXISTS geometries AS SELECT * FROM '{GEOMETRIES_TABLE}';"
    # )
    logger.debug(
        f"Tables loaded successfully in {time.time() - start_time:.2f} seconds."
    )

    return conn
