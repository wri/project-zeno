# Project Zeno - AOI Geometry Optimization Scripts

This directory contains scripts for optimizing geospatial data storage and access in Project Zeno by separating geometry from metadata.

## Overview

These scripts transform raw geospatial data from four different sources into a standardized database schema and export the processed data to parquet files for efficient access.

## Data Sources

1. **GADM** - Global Administrative Areas (countries, states, districts, etc.)
2. **KBA** - Key Biodiversity Areas (critical habitats and ecosystems)
3. **Landmark** - Indigenous and Community Lands
4. **WDPA** - World Database on Protected Areas

## Prerequisites

- DuckDB installed and accessible via command line
- Python 3.x with required packages: `duckdb`, `pandas`, `geopandas`, `requests`, `s3fs`
- Internet connection for downloading data sources
- AWS credentials configured for S3 access (for KBA, Landmark, WDPA data)

## Step-by-Step Process

### Step 0: Data Ingestion (Download and Load Raw Data)

Run the ingestion script to download and load raw geospatial data into DuckDB:

```bash
cd /path/to/project-zeno
python scripts/ingest_basemaps_to_duckdb.py
```

**What this script does:**

1. **Downloads GADM 4.1 data** - Global Administrative Areas
   - Downloads `gadm_410-levels.zip` (contains all administrative levels)
   - Extracts GeoPackage with 6 administrative layers (ADM_0 to ADM_5)
   - Processes all layers: countries, states/provinces, districts/counties, municipalities, localities, neighbourhoods

2. **Downloads additional data sources** - From S3 data lake (requires AWS credentials):
   - **KBA**: Key Biodiversity Areas from BirdLife International
   - **Landmark**: Indigenous and Community Lands
   - **WDPA**: World Database on Protected Areas

3. **Processes and standardizes data**:
   - Adds `subtype` classification for each administrative level
   - Creates unified `name` field combining hierarchical names
   - Converts geometry to WKB format for efficient DuckDB storage
   - Adds unique IDs (`gadm_id`, `id`) for each record

4. **Loads into DuckDB database**:
   - Creates `data/geocode/basemaps.duckdb` database
   - Loads spatial extensions
   - Creates tables: `gadm`, `kba`, `landmark`, `wdpa`

**Command line options:**
```bash
# Custom database location
python scripts/ingest_basemaps_to_duckdb.py --database data/geocode/basemaps.duckdb

# Custom temporary directory for downloads
python scripts/ingest_basemaps_to_duckdb.py --tempdir /tmp
```

### Step 1: Database Schema Processing

Run the SQL script to process and standardize the raw data tables:

```bash
cd /path/to/project-zeno
duckdb data/geocode/basemaps.duckdb < scripts/create_gadm_plus.sql
```

**What this script does:**

1. **Loads spatial extensions** - Enables DuckDB's spatial functionality
2. **Standardizes table schemas** - Ensures consistent column names across all tables:
   - Renames `id` columns to source-specific IDs (`gadm_id`, `kba_id`, etc.)
   - Creates standardized `name` fields by combining source-specific name fields
   - Adds `subtype` classification for each source
3. **Creates centralized geometry table** - Extracts all geometry data into a single `geometries` table with:
   - `source`: Data source identifier ('gadm', 'kba', 'landmark', 'wdpa')
   - `src_id`: Source-specific ID
   - `geometry`: Spatial geometry data
4. **Removes duplicate geometry** - Drops geometry columns from individual source tables
5. **Creates unified metadata table** - Builds `gadm_plus` table combining metadata from all sources
6. **Adds performance indexes** - Creates indexes for fast lookups and spatial queries

### Step 2: Export to Parquet Files

Run the Python script to export processed tables to parquet format:

```bash
python scripts/export_optimized_parquets.py
```

**What this script does:**

1. **Connects to DuckDB database** - Opens the processed database
2. **Exports individual source tables** - Creates parquet files for each source:
   - `gadm_no_geom.parquet` - GADM administrative areas (metadata only)
   - `kba_no_geom.parquet` - Key Biodiversity Areas (metadata only)
   - `landmark_no_geom.parquet` - Indigenous and Community Lands (metadata only)
   - `wdpa_no_geom.parquet` - Protected areas (metadata only)
3. **Exports unified tables** - Creates combined data files:
   - `geometries.parquet` - All geometry data with source identifiers
   - `gadm_plus.parquet` - Unified searchable metadata from all sources
4. **Applies compression** - Uses parquet's efficient columnar compression
5. **Reports export statistics** - Shows row counts for verification

## Output Files

After running both scripts, you'll have the following parquet files in `data/geocode/`:

| File | Description | Use Case |
|------|-------------|----------|
| `gadm_no_geom.parquet` | GADM metadata only | Source-specific queries |
| `kba_no_geom.parquet` | KBA metadata only | Source-specific queries |
| `landmark_no_geom.parquet` | Landmark metadata only | Source-specific queries |
| `wdpa_no_geom.parquet` | WDPA metadata only | Source-specific queries |
| `geometries.parquet` | All geometry data | Map rendering, spatial operations |
| `gadm_plus.parquet` | Unified metadata | AOI search and selection |

## Database Schema After Processing

### Individual Source Tables
- **gadm**: `gadm_id`, `name`, `subtype`, + original columns (no geometry)
- **kba**: `kba_id`, `name`, `subtype`, + original columns (no geometry)
- **landmark**: `landmark_id`, `landmark_name`, `name`, `subtype`, + original columns (no geometry)
- **wdpa**: `wdpa_id`, `wdpa_name`, `name`, `subtype`, + original columns (no geometry)

### Unified Tables
- **geometries**: `id`, `source`, `src_id`, `geometry`
- **gadm_plus**: `source`, `src_id`, `name`, `subtype`, `is_gadm`, `is_kba`, `is_landmark`, `is_wdpa`

## Integration

The processed data is used by:
- **Backend tools** (`src/tools/pick_aoi.py`) - Uses `gadm_plus.parquet` for AOI search
- **API endpoints** (`src/api/app.py`) - Uses `geometries.parquet` for geometry lookup
- **Frontend** - Receives metadata and fetches geometry separately via API

## Re-running the Process

To re-process the data (e.g., after updating source data):

### Complete Re-run (Fresh Data)
1. **Step 0**: Run `ingest_basemaps_to_duckdb.py` to download fresh data
2. **Step 1**: Run `create_gadm_plus.sql` to recreate processed tables
3. **Step 2**: Run `export_optimized_parquets.py` to regenerate parquet files
4. **Verify**: Check output files and row counts

### Partial Re-run (Existing Raw Data)
If raw data is already current, skip Step 0:
1. **Step 1**: Run `create_gadm_plus.sql` to recreate processed tables
2. **Step 2**: Run `export_optimized_parquets.py` to regenerate parquet files
3. **Verify**: Check output files and row counts

## Technical Details

### Geometry Table Schema
```sql
CREATE TABLE geometries (
    id INTEGER,
    source VARCHAR,      -- 'gadm', 'kba', 'landmark', 'wdpa'  
    src_id INTEGER,      -- Original table's primary key
    geometry GEOMETRY    -- Spatial geometry data
);
```

### Spatial Query Pattern
```sql
-- Find subregions within AOI (geometry used for filtering only)
WITH aoi AS (
    SELECT geometry FROM geometries 
    WHERE source = 'gadm' AND src_id = 123
)
SELECT t.* 
FROM kba_no_geom t
JOIN geometries g ON t.kba_id = g.src_id AND g.source = 'kba'
CROSS JOIN aoi
WHERE ST_Within(g.geometry, aoi.geometry);
```

This architecture optimizes both storage efficiency and query performance while maintaining clean separation between business logic and visualization concerns.
