#!/usr/bin/env python3
"""
ingest_basemaps_to_duckdb.py
~~~~~~~~~~~~~~~~~~~~~~~~~~

• Downloads GADM 4.1 “all-levels” archive
• Extracts the GeoPackage
• Loads the six administrative layers into GeoPandas
• Adds a `subtype` and fully-qualified `name`
• Writes the combined table to DuckDB with true geometry
"""

import argparse
import json
import logging
import zipfile
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import requests
import s3fs

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

GADM_ZIP_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/gadm_410-levels.zip"
# Define mappings between GADM layer names and their semantic subtypes
LAYER_SUBTYPES = {
    "ADM_0": "country",
    "ADM_1": "state-province",
    "ADM_2": "district-county",
    "ADM_3": "municipality",
    "ADM_4": "locality",
    "ADM_5": "neighbourhood",
}

# Reverse mapping for lookup by subtype
SUBTYPE_LAYERS = {
    "country": "GID_0",
    "state-province": "GID_1",
    "district-county": "GID_2",
    "municipality": "GID_3",
    "locality": "GID_4",
    "neighbourhood": "GID_5",
}

# Additional layers to load - NDJSON format
NDJSON_SOURCES = {
    "landmark": (
        "s3://gfw-data-lake/landmark_indigenous_and_community_lands/"
        "v202411/vector/epsg-4326/default.ndjson"
    ),
    "kba": (
        "s3://gfw-data-lake/birdlife_key_biodiversity_areas/"
        "v202106/vector/epsg-4326/birdlife_key_biodiversity_areas_v202106.ndjson"
    ),
    "wdpa": (
        "s3://gfw-data-lake/wdpa_protected_areas/"
        "v202407/vector/epsg-4326/wdpa_protected_areas_v202407.ndjson"
    ),
}


def download(url: str, dest: str) -> str:
    """Stream-download *url* into *dest* (skips if already present)."""
    dest = Path(dest)
    if dest.exists():
        logger.info(f"Using cached file → {dest}")
        return dest

    logger.info(f"Starting download from {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    logger.info(f"Downloaded {dest.stat().st_size/1e6:.1f} MB → {dest}")
    return dest


def extract_gpkg(zip_path: Path, out_dir: Path) -> Path:
    """Unzip and return the GeoPackage path."""
    logger.info(f"Extracting GeoPackage from {zip_path}")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)
    gpkg = out_dir / "gadm_410-levels.gpkg"
    if not gpkg.exists():
        raise FileNotFoundError("GeoPackage not found after extraction.")
    logger.info(f"Extracted GeoPackage → {gpkg}")
    return gpkg


def get_gadm_id(row):
    match row["subtype"]:
        case "country":
            return row[SUBTYPE_LAYERS["country"]]
        case "state-province":
            return row[SUBTYPE_LAYERS["state-province"]]
        case "district-county":
            return row[SUBTYPE_LAYERS["district-county"]]
        case "municipality":
            return row[SUBTYPE_LAYERS["municipality"]]
        case "locality":
            return row[SUBTYPE_LAYERS["locality"]]
        case "neighbourhood":
            return row[SUBTYPE_LAYERS["neighbourhood"]]


def get_kba_id(row):
    return row["sitrecid"]


def get_landmark_id(row):
    return row["gfw_fid"]


def get_wdpa_id(row):
    return row["wdpa_pid"]


def build_dataframe(gpkg: Path) -> gpd.GeoDataFrame:
    """Read all six layers, add subtype & qualified name, return one GeoDataFrame."""
    frames = []
    for layer, subtype in LAYER_SUBTYPES.items():
        df = gpd.read_file(gpkg, layer=layer)
        df["subtype"] = subtype
        frames.append(df)

    gdf = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), crs=frames[0].crs
    )

    # Build a single display name, ignoring NaNs / empty strings
    name_cols = ["NAME_5", "NAME_4", "NAME_3", "NAME_2", "NAME_1", "COUNTRY"]
    gdf["name"] = gdf.apply(
        lambda row: ", ".join(
            str(v)
            for v in (row[c] for c in name_cols)
            if pd.notna(v) and v != ""
        ),
        axis=1,
    )

    # DuckDB’s spatial extension works with WKB → convert for fast load
    gdf["geometry"] = gdf.geometry.apply(lambda geom: geom.wkb)

    # Add a unique id
    gdf["gadm_id"] = gdf.apply(get_gadm_id, axis=1)

    return gdf


def load_into_duckdb(
    gdf: gpd.GeoDataFrame, db_path: Path, table: str = "gadm"
) -> None:
    """Create a DuckDB DB (or connect), load the spatial extension, write table."""
    con = duckdb.connect(db_path)
    con.execute("INSTALL spatial; LOAD spatial;")
    con.register("gadm_view", gdf)

    create_sql = f"""
        CREATE OR REPLACE TABLE {table} AS
        SELECT
            * EXCLUDE geometry,
            ST_GeomFromWKB(geometry) AS geometry
        FROM gadm_view;
    """
    con.execute(create_sql)
    rows = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"✓ Loaded {rows:,} rows into {db_path} → table “{table}”")
    con.close()


def cached_ndjson_path(url: str, cache_dir: Path = Path("/tmp")) -> Path:
    """
    Return a local path for *url*, downloading once into *cache_dir*
    (skips if the file already exists).
    Works for plain HTTP/HTTPS as well as requester-pays S3 URLs.
    """
    dest = cache_dir / Path(url).name
    if dest.exists():
        logger.info(f"Using cached NDJSON → {dest}")
        return dest

    cache_dir.mkdir(parents=True, exist_ok=True)

    if url.startswith("s3://"):
        logger.info(f"Downloading from S3: {url}")
        fs = s3fs.S3FileSystem(requester_pays=True)
        fs.get(url, str(dest), recursive=False)
    else:  # HTTP/HTTPS
        logger.info(f"Downloading from HTTP: {url}")
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)

    logger.info(f"Downloaded NDJSON {dest.stat().st_size/1e6:.1f} MB → {dest}")
    return dest


def gdf_from_ndjson(
    table: str, url: str, cache_dir: Path = Path("/tmp")
) -> gpd.GeoDataFrame:
    """
    Download the NDJSON file once (into *cache_dir*), then read it
    into a GeoDataFrame. Geometry is converted to WKB for DuckDB.
    """
    ndjson_path = cached_ndjson_path(url, cache_dir)

    logger.info(f"Processing NDJSON file for {table} table")
    features = []
    with open(ndjson_path, "r") as f:
        for line in f:
            if line := line.strip():
                features.append(json.loads(line))

    logger.info(f"Creating GeoDataFrame from {len(features)} features")
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    gdf["geometry"] = gdf.geometry.apply(lambda g: g.wkb)

    match table:
        case "landmark":
            gdf["id"] = gdf.apply(get_landmark_id, axis=1)
        case "kba":
            gdf["id"] = gdf.apply(get_kba_id, axis=1)
        case "wdpa":
            gdf["id"] = gdf.apply(get_wdpa_id, axis=1)

    logger.info(f"Processed {table} table with {len(gdf)} records")
    return gdf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download GADM 4.1 and load all admin levels into DuckDB."
    )
    parser.add_argument(
        "-d",
        "--database",
        default="data/geocode/basemaps.duckdb",
        type=str,
        help="DuckDB database to create / append to",
    )
    parser.add_argument(
        "--tempdir",
        default="/tmp",
        type=str,
        help="Where to store the downloaded archive and extracted files",
    )
    parser.add_argument(
        "--table",
        default="gadm",
        type=str,
        help="Destination table name inside DuckDB",
    )
    args = parser.parse_args()

    logger.info("Starting GADM basemap ingestion process")
    logger.info(f"Target database: {args.database}")

    # Process GADM data
    zip_path = download(
        GADM_ZIP_URL, Path(args.tempdir) / "gadm_410-levels.zip"
    )
    gpkg_path = extract_gpkg(zip_path, Path(args.tempdir))
    logger.info("Building GADM dataframe from GeoPackage layers")
    gdf = build_dataframe(gpkg_path)
    logger.info(f"Loading GADM data into DuckDB table '{args.table}'")
    load_into_duckdb(gdf, Path(args.database), table=args.table)

    # Load additional layers
    logger.info(f"Loading {len(NDJSON_SOURCES)} additional data sources")
    for table, url in NDJSON_SOURCES.items():
        logger.info(f"Loading '{table}' table from {url}")
        ndjson_gdf = gdf_from_ndjson(table, url)
        load_into_duckdb(ndjson_gdf, Path(args.database), table=table)

    logger.info("Basemap ingestion completed successfully")

    print("✓ Done")


if __name__ == "__main__":
    main()
