import json
import os
from pathlib import Path

import geopandas as gpd
import requests
import s3fs
import shapely
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DB_URL = os.environ["DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)


def cached_ndjson_path(url: str, cache_dir: Path = Path("/tmp")) -> Path:
    """
    Return a local path for *url*, downloading once into *cache_dir*
    (skips if the file already exists).
    Works for plain HTTP/HTTPS as well as requester-pays S3 URLs.

    The cache name is the whole URL path, not the file name: the data lake
    names every dataset's export ``default.ndjson``.
    """
    dest = cache_dir / url.split("://", 1)[-1].replace("/", "__")
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


# Why the ingests repair shapes as a whole
# ----------------------------------------
# Some sources draw one area as overlapping parts. `build-aois` repairs each
# part on its own (repairing a huge multi-part shape whole can exhaust the
# backend), and that cannot remove an overlap between parts. Such a shape
# stays invalid in `aois`, and GEOS predicates (ST_Touches in the subregion
# query) raise on it. The ingests therefore repair invalid shapes whole, in
# Python: the GEOS "structure" repair unions overlapping parts, and it needs
# GEOS 3.10, newer than the database's. The largest invalid WDPA shape (4.85M
# points, 19,429 parts) takes about 20 s and 1.5 GB.


def _as_multipolygon(geom):
    """A repaired shape as a MultiPolygon: some staging columns are typed.

    A GeometryCollection keeps only its polygon parts, unioned so that
    overlapping parts do not make the MultiPolygon invalid. A collection with
    no polygon part becomes None.
    """
    if geom is None:
        return geom
    if geom.geom_type == "GeometryCollection":
        polygons = [
            part
            for part in shapely.get_parts(geom)
            if part.geom_type in ("Polygon", "MultiPolygon")
        ]
        if not polygons:
            return None
        geom = shapely.union_all(polygons)
    if geom.geom_type == "Polygon":
        return shapely.MultiPolygon([geom])
    return geom


def make_valid_polygons(geometry: gpd.GeoSeries) -> gpd.GeoSeries:
    """*geometry* with each invalid shape repaired as a whole.

    The "structure" repair unions overlapping parts and drops collapsed
    (line or point) leftovers. A repaired shape is a MultiPolygon. Valid
    shapes are left as they are, except a GeometryCollection: GEOS calls one
    valid even when its parts overlap, but a typed column rejects it.
    """
    invalid = ~geometry.is_valid | (geometry.geom_type == "GeometryCollection")
    if not invalid.any():
        return geometry
    repaired = geometry.copy()
    fixed = shapely.make_valid(
        geometry[invalid].values, method="structure", keep_collapsed=False
    )
    repaired[invalid] = gpd.GeoSeries(
        [_as_multipolygon(g) for g in fixed],
        index=geometry.index[invalid],
        crs=geometry.crs,
    )
    return repaired


def repair_invalid_geometries(
    table_name: str, column: str = "geometry"
) -> int:
    """Repair, in place, every invalid shape of a staging table.

    For a table loaded before its ingest repaired shapes: no download and no
    re-ingest. One row at a time, each its own transaction, so memory stays
    bounded and an interrupted run resumes where it stopped. Run
    `build-aois --source <source>` afterwards to carry the shapes into `aois`.
    Returns the number of shapes repaired.
    """
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    f"SELECT ctid::text FROM {table_name} "
                    f"WHERE {column} IS NOT NULL AND NOT ST_IsValid({column})"
                )
            )
            .scalars()
            .all()
        )
    print(f"Repairing {len(rows)} invalid shape(s) in {table_name}...")

    repaired = 0
    for i, ctid in enumerate(rows, start=1):
        with engine.begin() as conn:
            wkb = conn.execute(
                text(
                    f"SELECT ST_AsBinary({column}) FROM {table_name} "
                    "WHERE ctid = CAST(:ctid AS tid)"
                ),
                {"ctid": ctid},
            ).scalar()
            if wkb is None:
                continue
            geom = _as_multipolygon(
                shapely.make_valid(
                    shapely.from_wkb(bytes(wkb)),
                    method="structure",
                    keep_collapsed=False,
                )
            )
            conn.execute(
                text(
                    f"UPDATE {table_name} SET {column} = "
                    "ST_SetSRID(ST_GeomFromWKB(:wkb), 4326) "
                    "WHERE ctid = CAST(:ctid AS tid)"
                ),
                {"wkb": shapely.to_wkb(geom), "ctid": ctid},
            )
        repaired += 1
        if i % 50 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)}")
    print(f"✓ Repaired {repaired} shape(s) in {table_name}")
    return repaired
