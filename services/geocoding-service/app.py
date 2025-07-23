import json
import asyncio
import logging
from typing import List, Dict, Any
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


def configure_thread_pool():
    """Configure asyncio with a thread pool for database operations."""
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="db-worker")
    loop.set_default_executor(executor)
    logger.info("Configured thread pool with 4 workers for database operations")


# Simple in-memory cache for query results
# note that lru_cache from standard library is not suitable for async functions
query_cache: Dict[str, Any] = {}


def get_cache_key(query_type: str, **params) -> str:
    """Generate a cache key for query parameters."""
    key_data = f"{query_type}:{str(sorted(params.items()))}"
    return hashlib.md5(key_data.encode()).hexdigest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_thread_pool()
    yield
    # Shutdown - cleanup if needed
    pass


app = FastAPI(
    title="Geocoding Service",
    description="Area of Interest database query service",
    lifespan=lifespan,
)

GADM_TABLE = "data/geocode/exports/gadm.parquet"
KBA_TABLE = "data/geocode/exports/kba.parquet"
LANDMARK_TABLE = "data/geocode/exports/landmark.parquet"
WDPA_TABLE = "data/geocode/exports/wdpa.parquet"


class AOISearchRequest(BaseModel):
    place_name: str
    result_limit: int = 10


class AOISearchResponse(BaseModel):
    results: List[dict]


class SubregionSearchRequest(BaseModel):
    subregion_name: str
    source: str
    src_id: int


class SubregionSearchResponse(BaseModel):
    results: List[dict]


class AOIByIdRequest(BaseModel):
    source: str
    src_id: int


class AOIByIdResponse(BaseModel):
    result: dict


class ConnectionManager:
    """Simple connection manager that creates connections per request."""

    def __init__(self):
        self.local_path = "local_basemaps.duckdb"

    def get_connection(self):
        """Create and configure a DuckDB connection with necessary extensions."""
        conn = duckdb.connect(self.local_path, read_only=True)
        conn.sql("INSTALL spatial; LOAD spatial;")

        # Enable parallel processing in DuckDB
        conn.execute("SET threads=4;")
        
        # Create indexes for faster ID-based lookups
        try:
            # Index on GADM table
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_gadm_id ON '{GADM_TABLE}' (gadm_id);")
            # Index on KBA table  
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_kba_id ON '{KBA_TABLE}' (kba_id);")
            # Index on Landmark table
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_landmark_id ON '{LANDMARK_TABLE}' (landmark_id);")
            # Index on WDPA table
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_wdpa_id ON '{WDPA_TABLE}' (wdpa_id);")
            
            logger.info("Created indexes on ID columns for faster lookups")
        except Exception as e:
            logger.warning(f"Could not create indexes (may not be supported on Parquet): {e}")

        return conn


connection_manager = ConnectionManager()


async def query_aoi_database(
    connection: duckdb.DuckDBPyConnection,
    place_name: str,
    result_limit: int = 10,
):
    """Query the Overture database for location information."""
    sql_query = f"""
        SELECT
            *,
            jaro_winkler_similarity(LOWER(name), LOWER('{place_name}')) AS similarity_score
        FROM gadm_plus_search
        ORDER BY similarity_score DESC
        LIMIT {result_limit}
    """
    logger.info(f"Executing AOI query: {sql_query}")

    # Run the query in a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    query_results = await loop.run_in_executor(None, connection.sql, sql_query)
    results_df = await loop.run_in_executor(None, query_results.df)

    logger.info(f"AOI query results: {results_df}")
    return results_df


async def query_subregion_database(
    connection, subregion_name: str, source: str, src_id: int
):
    """Query the right table in basemaps database for subregions based on the selected AOI."""

    # Map subregion names to table names
    table_mapping = {
        "country": GADM_TABLE,
        "state": GADM_TABLE,
        "district": GADM_TABLE,
        "municipality": GADM_TABLE,
        "locality": GADM_TABLE,
        "neighbourhood": GADM_TABLE,
        "kba": KBA_TABLE,
        "wdpa": WDPA_TABLE,
        "landmark": LANDMARK_TABLE,
    }

    if subregion_name not in table_mapping:
        raise ValueError(
            f"Subregion: {subregion_name} does not match to any table in basemaps database."
        )

    table_name = table_mapping[subregion_name]

    sql_query = f"""
    WITH aoi AS (
        SELECT geometry AS geom
        FROM 'data/geocode/exports/{source}.parquet'
        WHERE {source}_id = {src_id}
    )
    SELECT t.* EXCLUDE geometry, ST_AsGeoJSON(t.geometry) as geometry
    FROM '{table_name}' AS t, aoi
    WHERE ST_Within(t.geometry, aoi.geom);
    """
    logger.info(f"Executing subregion query: {sql_query}")

    # Run the query in a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    query_result = await loop.run_in_executor(None, connection.execute, sql_query)
    results = await loop.run_in_executor(None, query_result.df)

    # Parse GeoJSON strings in the results
    if not results.empty and "geometry" in results.columns:
        for idx, row in results.iterrows():
            if row["geometry"] is not None and isinstance(row["geometry"], str):
                try:
                    results.at[idx, "geometry"] = json.loads(row["geometry"])
                except json.JSONDecodeError as e:
                    logger.info(
                        f"Failed to parse GeoJSON for subregion {row.get('name', 'Unknown')}: {e}"
                    )
                    results.at[idx, "geometry"] = None

    return results


async def get_aoi_by_id(connection, source: str, src_id: int):
    """Get specific AOI by source and ID."""

    # Check cache first
    cache_key = get_cache_key("aoi_by_id", source=source, src_id=src_id)
    if cache_key in query_cache:
        logger.info(f"Cache hit for AOI by ID: {source}:{src_id}")
        return query_cache[cache_key]

    # Map source to table and ID column
    source_mapping = {
        "gadm": (GADM_TABLE, "gadm_id"),
        "kba": (KBA_TABLE, "kba_id"),
        "landmark": (LANDMARK_TABLE, "landmark_id"),
        "wdpa": (WDPA_TABLE, "wdpa_id"),
    }

    if source not in source_mapping:
        raise ValueError(
            f"Source: {source} does not match to any table in basemaps database."
        )

    table_name, id_column = source_mapping[source]

    sql_query = f"""
    SELECT * EXCLUDE geometry, ST_AsGeoJSON(geometry) as geometry
    FROM '{table_name}'
    WHERE {id_column} = {src_id}
    """

    logger.info(f"Executing AOI by ID query: {sql_query}")

    # Run the query in a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    query_result = await loop.run_in_executor(None, connection.sql, sql_query)
    results = await loop.run_in_executor(None, query_result.df)

    if results.empty:
        raise ValueError(f"No AOI found for source: {source}, ID: {src_id}")

    result = results.iloc[0].to_dict()

    # Parse the GeoJSON string into a Python dictionary
    if "geometry" in result and result["geometry"] is not None:
        try:
            if isinstance(result["geometry"], str):
                result["geometry"] = json.loads(result["geometry"])
                logger.info(
                    f"Parsed GeoJSON geometry for AOI: {result.get('name', 'Unknown')}"
                )
        except json.JSONDecodeError as e:
            logger.info(
                f"Failed to parse GeoJSON for AOI {result.get('name', 'Unknown')}: {e}"
            )
            result["geometry"] = None
    else:
        logger.info(f"No geometry found for AOI: {result.get('name', 'Unknown')}")

    # Cache the result with eviction
    if len(query_cache) >= 1000:
        # Remove oldest item (first inserted) to make room
        oldest_key = next(iter(query_cache))
        del query_cache[oldest_key]
        logger.info(f"Evicted oldest cache entry: {oldest_key}")

    query_cache[cache_key] = result
    logger.info(f"Cached result for AOI by ID: {source}:{src_id}")

    return result


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "geocoding-service"}


@app.post("/aoi/search", response_model=AOISearchResponse)
async def search_aoi(request: AOISearchRequest):
    """Search for areas of interest by place name."""
    connection = None
    try:
        connection = connection_manager.get_connection()
        results_df = await query_aoi_database(
            connection, request.place_name, request.result_limit
        )

        # Convert DataFrame to list of dictionaries
        results = results_df.to_dict(orient="records")

        return AOISearchResponse(results=results)

    except Exception as e:
        logger.error(f"Error in AOI search: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if connection:
            connection.close()


@app.post("/aoi/subregions", response_model=SubregionSearchResponse)
async def search_subregions(request: SubregionSearchRequest):
    """Search for subregions within an AOI."""
    connection = None
    try:
        connection = connection_manager.get_connection()
        results_df = await query_subregion_database(
            connection, request.subregion_name, request.source, request.src_id
        )

        # Convert DataFrame to list of dictionaries
        results = results_df.to_dict(orient="records")

        return SubregionSearchResponse(results=results)

    except Exception as e:
        logger.error(f"Error in subregion search: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if connection:
            connection.close()


@app.post("/aoi/by-id", response_model=AOIByIdResponse)
async def get_aoi_by_source_id(request: AOIByIdRequest):
    """Get specific AOI by source and ID."""
    connection = None
    try:
        connection = connection_manager.get_connection()
        result = await get_aoi_by_id(connection, request.source, request.src_id)

        return AOIByIdResponse(result=result)

    except Exception as e:
        logger.error(f"Error getting AOI by ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
