import json
from pathlib import Path
import requests
import geopandas as gpd
import s3fs
import os
from sqlalchemy import create_engine, text
from src.utils.env_loader import load_environment_variables

load_environment_variables()


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

    print(f"✓ Downloaded {dest.stat().st_size/1e6:.1f} MB")
    return dest


def gdf_from_ndjson(url: str, cache_dir: Path = Path("/tmp")) -> gpd.GeoDataFrame:
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


def ingest_to_postgis(
    table_name: str, gdf: gpd.GeoDataFrame, chunk_size: int = 10000
) -> None:
    """Ingest the GeoDataFrame to PostGIS database in chunks."""
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)

    # Ensure PostGIS extension is enabled
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.commit()

    gdf_copy = gdf.copy()
    gdf_copy["geometry"] = gpd.GeoSeries.from_wkb(gdf_copy["geometry"], crs="EPSG:4326")

    total_records = len(gdf_copy)
    print(f"Ingesting {total_records} records in chunks of {chunk_size}...")

    # Process in chunks
    for i in range(0, total_records, chunk_size):
        chunk = gdf_copy.iloc[i : i + chunk_size]
        if_exists_param = "replace" if i == 0 else "append"

        chunk.to_postgis(table_name, engine, if_exists=if_exists_param, index=False)

        records_processed = min(i + chunk_size, total_records)
        print(f"✓ Processed {records_processed}/{total_records} records")

    # Ensure all geometries have correct SRID and create spatial index
    with engine.connect() as conn:
        conn.execute(text(f"UPDATE {table_name} SET geometry = ST_SetSRID(geometry, 4326) WHERE ST_SRID(geometry) = 0;"))
        conn.commit()
        print(f"✓ Updated SRID to 4326 for geometries with undefined SRID")
        
        # Create spatial index using bounding boxes to avoid size limits for complex geometries
        index_name = f"idx_{table_name}_geom"
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} USING GIST (ST_Envelope(geometry));"))
        conn.commit()
        print(f"✓ Created spatial index {index_name} on {table_name}")

    print(f"✓ Ingested {total_records} records to PostGIS table '{table_name}'")
