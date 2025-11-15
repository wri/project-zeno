"""
Ontario Provincial Parks Ingestion Script
==========================================

This script downloads and ingests Ontario Provincial Parks data from Ontario GeoHub
into the PostgreSQL/PostGIS database.

Data Source: Ontario GeoHub - Provincial Parks
License: Open Government License - Ontario
"""

import os
import asyncio
import logging
from typing import Dict, Any, List
import asyncpg
from urllib.request import urlretrieve
import geopandas as gpd
from pathlib import Path
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DATA_DIR = Path("data/ontario/parks")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Ontario GeoHub API endpoints
ONTARIO_GEOHUB_BASE = "https://ws.lioservices.lrc.gov.on.ca/arcgis1071a/rest/services"

# Provincial Parks dataset (you'll need to find the exact service URL)
PARKS_SERVICE_URL = f"{ONTARIO_GEOHUB_BASE}/LIO_OPEN_DATA/LIO_Open05/MapServer/12"  # Example
PARKS_GEOJSON_URL = "https://geohub.lio.gov.on.ca/datasets/provincial-parks/data.geojson"  # Alternative

# Database connection (from environment)
DATABASE_URL = os.getenv("DATABASE_URL")

# Park class mapping
PARK_CLASS_MAP = {
    "Wilderness": "wilderness",
    "Natural Environment": "natural_environment",
    "Waterway": "waterway",
    "Recreational": "recreational",
    "Nature Reserve": "nature_reserve",
    "Cultural Heritage": "cultural_heritage",
    "Recreation Trail": "recreation_trail"
}


async def create_connection() -> asyncpg.Connection:
    """Create database connection"""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")
    
    return await asyncpg.connect(DATABASE_URL)


async def download_parks_data() -> gpd.GeoDataFrame:
    """
    Download Ontario Provincial Parks data from Ontario GeoHub
    
    Returns:
        GeoDataFrame with parks data
    """
    logger.info("Downloading Ontario Provincial Parks data...")
    
    # Option 1: Download from GeoJSON endpoint (if available)
    parks_file = DATA_DIR / "provincial_parks.geojson"
    
    if not parks_file.exists():
        try:
            logger.info(f"Downloading from: {PARKS_GEOJSON_URL}")
            urlretrieve(PARKS_GEOJSON_URL, parks_file)
            logger.info(f"Downloaded to: {parks_file}")
        except Exception as e:
            logger.error(f"Failed to download from GeoJSON URL: {e}")
            logger.info("Trying ArcGIS REST API...")
            
            # Option 2: Use ArcGIS REST API to get data
            # You may need to use arcgis2geobuf or similar tool
            # Or use the requests library to query the REST API
            # For now, we'll assume manual download or use arcgis library
            raise NotImplementedError(
                "Please download provincial parks data manually from Ontario GeoHub "
                "and place it in data/ontario/parks/provincial_parks.geojson"
            )
    
    # Load the GeoJSON
    logger.info("Loading parks data into GeoDataFrame...")
    gdf = gpd.read_file(parks_file)
    
    logger.info(f"Loaded {len(gdf)} parks")
    logger.info(f"Columns: {gdf.columns.tolist()}")
    
    return gdf


def transform_parks_data(gdf: gpd.GeoDataFrame) -> List[Dict[str, Any]]:
    """
    Transform parks GeoDataFrame into format for database insertion
    
    Args:
        gdf: GeoDataFrame with parks data
        
    Returns:
        List of dictionaries ready for database insertion
    """
    logger.info("Transforming parks data...")
    
    # Ensure CRS is EPSG:4326
    if gdf.crs is None:
        logger.warning("No CRS found, assuming EPSG:4326")
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        logger.info(f"Reprojecting from {gdf.crs} to EPSG:4326")
        gdf = gdf.to_crs("EPSG:4326")
    
    parks = []
    
    for idx, row in gdf.iterrows():
        # Adapt field names based on actual Ontario GeoHub schema
        # These are examples - adjust based on actual data
        
        # Convert geometry to WKT
        geometry_wkt = row.geometry.wkt
        
        # Calculate area in hectares
        area_ha = row.geometry.area * 10000  # Rough conversion, better to use geography
        
        park = {
            "park_id": row.get("PARK_ID", f"ONT-{idx}"),
            "park_name": row.get("PARK_NAME", row.get("NAME", "Unknown")),
            "park_class": PARK_CLASS_MAP.get(
                row.get("PARK_CLASS", row.get("CLASS")), 
                "unknown"
            ),
            "geometry": geometry_wkt,
            "size_ha": area_ha,
            "regulation_date": row.get("REGULATION_DATE"),
            "operating_season": row.get("OPERATING_SEASON"),
            "facilities": json.dumps({
                "camping": row.get("CAMPING", False),
                "trails": row.get("TRAILS", False),
                "backcountry": row.get("BACKCOUNTRY", False),
                "day_use": row.get("DAY_USE", True)
            }),
            "website": row.get("WEBSITE", row.get("URL")),
            "description": row.get("DESCRIPTION", "")
        }
        
        parks.append(park)
    
    logger.info(f"Transformed {len(parks)} parks")
    return parks


async def ingest_parks(conn: asyncpg.Connection, parks: List[Dict[str, Any]]) -> int:
    """
    Ingest parks data into database
    
    Args:
        conn: Database connection
        parks: List of park dictionaries
        
    Returns:
        Number of parks ingested
    """
    logger.info("Ingesting parks into database...")
    
    # Clear existing data (optional - comment out to preserve existing data)
    # await conn.execute("TRUNCATE ontario_provincial_parks CASCADE")
    # logger.info("Cleared existing parks data")
    
    # Prepare insert statement
    insert_query = """
        INSERT INTO ontario_provincial_parks (
            park_id, park_name, park_class, geometry, size_ha,
            regulation_date, operating_season, facilities, website, description
        ) VALUES (
            $1, $2, $3, ST_GeomFromText($4, 4326), $5,
            $6, $7, $8::jsonb, $9, $10
        )
        ON CONFLICT (park_id) DO UPDATE SET
            park_name = EXCLUDED.park_name,
            park_class = EXCLUDED.park_class,
            geometry = EXCLUDED.geometry,
            size_ha = EXCLUDED.size_ha,
            regulation_date = EXCLUDED.regulation_date,
            operating_season = EXCLUDED.operating_season,
            facilities = EXCLUDED.facilities,
            website = EXCLUDED.website,
            description = EXCLUDED.description,
            updated_at = NOW()
    """
    
    # Batch insert
    inserted = 0
    for park in parks:
        try:
            await conn.execute(
                insert_query,
                park["park_id"],
                park["park_name"],
                park["park_class"],
                park["geometry"],
                park["size_ha"],
                park.get("regulation_date"),
                park.get("operating_season"),
                park.get("facilities", "{}"),
                park.get("website"),
                park.get("description", "")
            )
            inserted += 1
            
            if inserted % 50 == 0:
                logger.info(f"Inserted {inserted}/{len(parks)} parks...")
                
        except Exception as e:
            logger.error(f"Failed to insert park {park['park_name']}: {e}")
            continue
    
    logger.info(f"Successfully inserted {inserted} parks")
    return inserted


async def validate_data(conn: asyncpg.Connection) -> Dict[str, Any]:
    """
    Validate ingested data
    
    Args:
        conn: Database connection
        
    Returns:
        Validation results
    """
    logger.info("Validating ingested data...")
    
    results = {}
    
    # Count total parks
    count = await conn.fetchval("SELECT COUNT(*) FROM ontario_provincial_parks")
    results["total_parks"] = count
    logger.info(f"Total parks: {count}")
    
    # Count by class
    class_counts = await conn.fetch("""
        SELECT park_class, COUNT(*) as count
        FROM ontario_provincial_parks
        GROUP BY park_class
        ORDER BY count DESC
    """)
    results["parks_by_class"] = {row["park_class"]: row["count"] for row in class_counts}
    logger.info(f"Parks by class: {results['parks_by_class']}")
    
    # Check for invalid geometries
    invalid_geom = await conn.fetchval("""
        SELECT COUNT(*) FROM ontario_provincial_parks
        WHERE NOT ST_IsValid(geometry)
    """)
    results["invalid_geometries"] = invalid_geom
    if invalid_geom > 0:
        logger.warning(f"Found {invalid_geom} parks with invalid geometries!")
    else:
        logger.info("All geometries are valid ✓")
    
    # Check projection
    projection = await conn.fetchval("""
        SELECT ST_SRID(geometry) FROM ontario_provincial_parks LIMIT 1
    """)
    results["projection"] = projection
    if projection == 4326:
        logger.info(f"Projection is correct: EPSG:{projection} ✓")
    else:
        logger.warning(f"Projection is EPSG:{projection}, expected 4326!")
    
    # Calculate total protected area
    total_area = await conn.fetchval("""
        SELECT SUM(size_ha) FROM ontario_provincial_parks
    """)
    results["total_area_ha"] = total_area
    logger.info(f"Total protected area: {total_area:,.0f} hectares ({total_area/10000:,.0f} km²)")
    
    # Find largest parks
    largest_parks = await conn.fetch("""
        SELECT park_name, park_class, size_ha
        FROM ontario_provincial_parks
        ORDER BY size_ha DESC
        LIMIT 5
    """)
    results["largest_parks"] = [
        {
            "name": row["park_name"], 
            "class": row["park_class"],
            "size_ha": row["size_ha"]
        } 
        for row in largest_parks
    ]
    logger.info("Largest parks:")
    for park in results["largest_parks"]:
        logger.info(f"  - {park['name']}: {park['size_ha']:,.0f} ha ({park['class']})")
    
    return results


async def main():
    """Main ingestion process"""
    logger.info("=" * 80)
    logger.info("Ontario Provincial Parks Ingestion")
    logger.info("=" * 80)
    
    try:
        # Download data
        gdf = await download_parks_data()
        
        # Transform data
        parks = transform_parks_data(gdf)
        
        # Connect to database
        conn = await create_connection()
        
        try:
            # Ingest data
            inserted_count = await ingest_parks(conn, parks)
            
            # Validate data
            validation_results = await validate_data(conn)
            
            logger.info("=" * 80)
            logger.info("Ingestion Complete!")
            logger.info(f"Inserted: {inserted_count} parks")
            logger.info(f"Total in database: {validation_results['total_parks']} parks")
            logger.info("=" * 80)
            
            # Expected values for Ontario
            if validation_results['total_parks'] < 300:
                logger.warning(f"Expected ~340 parks, found {validation_results['total_parks']}")
            elif validation_results['total_parks'] > 400:
                logger.warning(f"More parks than expected: {validation_results['total_parks']} (expected ~340)")
            else:
                logger.info(f"Park count looks good: {validation_results['total_parks']} ✓")
            
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
