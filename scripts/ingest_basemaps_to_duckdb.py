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
import zipfile
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import requests
import s3fs

GADM_ZIP_URL = "https://geodata.ucdavis.edu/gadm/gadm4.1/gadm_410-levels.zip"
LAYER_SUBTYPES = {
    "ADM_0": "country",
    "ADM_1": "state-province",
    "ADM_2": "district-county",
    "ADM_3": "municipality",
    "ADM_4": "locality",
    "ADM_5": "neighbourhood",
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
        print(f"✓ Using cached file → {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    print(f"✓ Downloaded {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def extract_gpkg(zip_path: Path, out_dir: Path) -> Path:
    """Unzip and return the GeoPackage path."""
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out_dir)
    gpkg = out_dir / "gadm_410-levels.gpkg"
    if not gpkg.exists():
        raise FileNotFoundError("GeoPackage not found after extraction.")
    print(f"✓ Extracted → {gpkg}")
    return gpkg


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
    gdf["gadm_id"] = gdf.index

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
        print(f"✓ Using cached NDJSON → {dest}")
        return dest

    cache_dir.mkdir(parents=True, exist_ok=True)

    if url.startswith("s3://"):
        fs = s3fs.S3FileSystem(requester_pays=True)
        print(f"⇣ Downloading {url} → {dest}")
        fs.get(url, str(dest), recursive=False)
    else:  # HTTP/HTTPS
        print(f"⇣ Downloading {url} → {dest}")
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)

    print(f"✓ Downloaded {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def gdf_from_ndjson(
    url: str, cache_dir: Path = Path("/tmp")
) -> gpd.GeoDataFrame:
    """
    Download the NDJSON file once (into *cache_dir*), then read it
    into a GeoDataFrame. Geometry is converted to WKB for DuckDB.
    """
    ndjson_path = cached_ndjson_path(url, cache_dir)

    features = []
    with open(ndjson_path, "r") as f:
        for line in f:
            if line := line.strip():
                features.append(json.loads(line))

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    gdf["geometry"] = gdf.geometry.apply(lambda g: g.wkb)
    gdf["id"] = gdf.index
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

    zip_path = download(
        GADM_ZIP_URL, Path(args.tempdir) / "gadm_410-levels.zip"
    )
    gpkg_path = extract_gpkg(zip_path, Path(args.tempdir))
    gdf = build_dataframe(gpkg_path)
    load_into_duckdb(gdf, Path(args.database), table=args.table)

    # Load additional layers
    for table, url in NDJSON_SOURCES.items():
        print(f"→ Loading “{table}” from {url}")
        ndjson_gdf = gdf_from_ndjson(url, Path(args.tempdir))
        load_into_duckdb(ndjson_gdf, Path(args.database), table=table)

    print("✓ Done")


if __name__ == "__main__":
    main()
