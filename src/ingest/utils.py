import json
import os
from pathlib import Path

import geopandas as gpd
import requests
import s3fs
from sqlalchemy import create_engine, text

from src.utils.env_loader import load_environment_variables

load_environment_variables()

DB_URL = os.environ["DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)


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


def gdf_from_ndjson_chunked(
    url: str, chunk_size: int = 1000, cache_dir: Path = Path("/tmp")
):
    """
    Download the NDJSON file once (into *cache_dir*), then yield
    GeoDataFrame chunks for processing.
    """
    ndjson_path = cached_ndjson_path(url, cache_dir)

    features = []
    processed_records = 0

    with open(ndjson_path, "r") as f:
        for line in f:
            if line := line.strip():
                features.append(json.loads(line))

                if len(features) >= chunk_size:
                    # Process this chunk
                    gdf = gpd.GeoDataFrame.from_features(
                        features, crs="EPSG:4326"
                    )
                    gdf["id"] = range(
                        processed_records, processed_records + len(gdf)
                    )

                    processed_records += len(features)

                    yield gdf

                    print(f"Processed {processed_records} records so far...")
                    # Reset for next chunk
                    features = []

    # Process remaining features
    if features:
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        gdf["id"] = range(processed_records, processed_records + len(gdf))

        processed_records += len(features)
        print(
            f"✓ Yielding final chunk with {len(features)} records (total processed: {processed_records})"
        )

        yield gdf


def ingest_to_postgis(
    table_name: str,
    gdf: gpd.GeoDataFrame,
    chunk_size: int = 1000,
    if_exists: str = "replace",
) -> None:
    """Ingest the GeoDataFrame to PostGIS database in chunks."""
    database_url = DB_URL
    engine = create_engine(database_url)

    # Ensure PostGIS extension is enabled
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
        conn.commit()

    gdf_copy = gdf.copy()
    gdf_copy["geometry"] = gpd.GeoSeries(gdf_copy["geometry"], crs="EPSG:4326")

    total_records = len(gdf_copy)

    # Process in chunks
    for i in range(0, total_records, chunk_size):
        chunk = gdf_copy.iloc[i : i + chunk_size]
        if_exists_param = if_exists if i == 0 else "append"

        chunk.to_postgis(
            table_name, engine, if_exists=if_exists_param, index=False
        )

    # Ensure all geometries have correct SRID and create spatial index
    with engine.connect() as conn:
        conn.execute(
            text(
                f"UPDATE {table_name} SET geometry = ST_SetSRID(geometry, 4326) WHERE ST_SRID(geometry) = 0;"
            )
        )
        conn.commit()
    print(
        f"✓ Ingested {total_records} records to PostGIS table '{table_name}'"
    )


def create_geometry_index_if_not_exists(
    table_name: str, index_name: str, column: str = "geometry"
) -> None:
    """Create a spatial index on the specified table and column if it does not exist."""
    database_url = DB_URL
    engine = create_engine(database_url)

    with engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} USING GIST (ST_Envelope({column}));"
            )
        )
        conn.commit()
        print(f"✓ Created spatial index {index_name} on {table_name}")


def create_text_search_index_if_not_exists(
    table_name: str, index_name: str, column: str = "name"
) -> None:
    """Create a GIN trigram index on the specified table and column for text search if it does not exist."""
    database_url = DB_URL
    engine = create_engine(database_url)

    with engine.connect() as conn:
        # Ensure pg_trgm extension is enabled
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))

        # Create GIN index for trigram-based text search
        conn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} USING GIN ({column} gin_trgm_ops);"
            )
        )
        conn.commit()
        print(
            f"✓ Created text search index {index_name} on {table_name}.{column}"
        )


def create_id_index_if_not_exists(
    table_name: str, index_name: str, column: str
) -> None:
    """Create a B-tree index on the specified ID column if it does not exist."""
    database_url = DB_URL
    engine = create_engine(database_url)

    with engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column});"
            )
        )
        conn.commit()
        print(f"✓ Created ID index {index_name} on {table_name}.{column}")
