import json
import os
import time
from functools import lru_cache
from typing import List

import duckdb
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()

app = FastAPI(
    title="AOI Service", description="Area of Interest database query service"
)

GADM_TABLE = "data/geocode/exports/gadm.parquet"
KBA_TABLE = "data/geocode/exports/kba.parquet"
LANDMARK_TABLE = "data/geocode/exports/landmark.parquet"
WDPA_TABLE = "data/geocode/exports/wdpa.parquet"
GADM_PLUS_SEARCH_TABLE = "data/geocode/exports/gadm_plus_search.parquet"


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


@lru_cache(maxsize=1)
def get_db_connection(local_path: str = "local_basemaps.duckdb"):
    """Create and configure a DuckDB connection with necessary extensions."""
    start_time = time.time()
    conn = duckdb.connect(local_path)
    conn.sql("INSTALL spatial; LOAD spatial;")
    conn.sql("INSTALL httpfs; LOAD httpfs;")

    print(
        f"DuckDB connection created and extensions installed in {time.time() - start_time:.2f} seconds."
    )

    # Setup S3 access
    start_time = time.time()
    conn.execute(f"SET s3_region='{os.getenv('AWS_DEFAULT_REGION', 'us-east-1')}';")
    conn.execute(f"SET s3_access_key_id='{os.getenv('AWS_ACCESS_KEY_ID')}';")
    conn.execute(f"SET s3_secret_access_key='{os.getenv('AWS_SECRET_ACCESS_KEY')}';")

    print(f"S3 access setup in {time.time() - start_time:.2f} seconds.")

    # Load tables
    start_time = time.time()
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS gadm_plus_search AS SELECT * FROM '{GADM_PLUS_SEARCH_TABLE}';"
    )

    print(f"Tables loaded successfully in {time.time() - start_time:.2f} seconds.")

    return conn


def query_aoi_database(
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
    print(f"Executing AOI query: {sql_query}")
    query_results = connection.sql(sql_query)
    results_df = query_results.df()
    print(f"AOI query results: {results_df}")
    return results_df


def query_subregion_database(connection, subregion_name: str, source: str, src_id: int):
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
    print(f"Executing subregion query: {sql_query}")
    results = connection.execute(sql_query).df()

    # Parse GeoJSON strings in the results
    if not results.empty and "geometry" in results.columns:
        for idx, row in results.iterrows():
            if row["geometry"] is not None and isinstance(row["geometry"], str):
                try:
                    results.at[idx, "geometry"] = json.loads(row["geometry"])
                except json.JSONDecodeError as e:
                    print(
                        f"Failed to parse GeoJSON for subregion {row.get('name', 'Unknown')}: {e}"
                    )
                    results.at[idx, "geometry"] = None

    return results


def get_aoi_by_id(connection, source: str, src_id: int):
    """Get specific AOI by source and ID."""

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

    print(f"Executing AOI by ID query: {sql_query}")
    results = connection.sql(sql_query).df()

    if results.empty:
        raise ValueError(f"No AOI found for source: {source}, ID: {src_id}")

    result = results.iloc[0].to_dict()

    # Parse the GeoJSON string into a Python dictionary
    if "geometry" in result and result["geometry"] is not None:
        try:
            if isinstance(result["geometry"], str):
                result["geometry"] = json.loads(result["geometry"])
                print(
                    f"Parsed GeoJSON geometry for AOI: {result.get('name', 'Unknown')}"
                )
        except json.JSONDecodeError as e:
            print(
                f"Failed to parse GeoJSON for AOI {result.get('name', 'Unknown')}: {e}"
            )
            result["geometry"] = None
    else:
        print(f"No geometry found for AOI: {result.get('name', 'Unknown')}")

    return result


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "geocoding-service"}


@app.post("/aoi/search", response_model=AOISearchResponse)
async def search_aoi(request: AOISearchRequest):
    """Search for areas of interest by place name."""
    try:
        connection = get_db_connection()
        results_df = query_aoi_database(
            connection, request.place_name, request.result_limit
        )

        # Convert DataFrame to list of dictionaries
        results = results_df.to_dict(orient="records")

        return AOISearchResponse(results=results)

    except Exception as e:
        print(f"Error in AOI search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/aoi/subregions", response_model=SubregionSearchResponse)
async def search_subregions(request: SubregionSearchRequest):
    """Search for subregions within an AOI."""
    try:
        connection = get_db_connection()
        results_df = query_subregion_database(
            connection, request.subregion_name, request.source, request.src_id
        )

        # Convert DataFrame to list of dictionaries
        results = results_df.to_dict(orient="records")

        return SubregionSearchResponse(results=results)

    except Exception as e:
        print(f"Error in subregion search: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/aoi/by-id", response_model=AOIByIdResponse)
async def get_aoi_by_source_id(request: AOIByIdRequest):
    """Get specific AOI by source and ID."""
    try:
        connection = get_db_connection()
        result = get_aoi_by_id(connection, request.source, request.src_id)

        return AOIByIdResponse(result=result)

    except Exception as e:
        print(f"Error getting AOI by ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
