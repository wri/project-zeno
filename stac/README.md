# STAC Ingestion for Zeno

## Installation

1. Install dependencies:

   ```bash
   uv pip install -r requirements.txt
   ```

2. Set up environment variables in `env/.env_localhost`:

   ```bash
   PGHOST=localhost
   PGPORT=5432
   PGDATABASE=pgstac
   PGUSER=your_username
   PGPASSWORD=your_password
   AWS_ACCESS_KEY_ID="***"
   AWS_SECRET_ACCESS_KEY="***"
   ```

## Usage

### Running the ingestion scripts

1. Activate the virtual environment
2. Run the main script:

   ```bash
   ingest_all.sh
   ```

## COG Creation Scripts

These scripts only have been used once to create global COG files for
Land cover and natural lands. Re-run manually when new data updates
are available.

**Requirements:** `uv`, `gsutil`, GDAL tools

### merge_global_land_cover.sh

Creates global Cloud-Optimized GeoTIFF (COG) files from Global Land Cover
data for years 2016-2024.

**Usage:** `./merge_global_land_cover.sh <local_dir>`

**What it does:**
- Downloads tiles from Google Cloud Storage (`gs://lcl_tiles/LCL_landCover/v2/`)
- Creates VRT files combining all tiles for each year
- Converts to COG format with LZW compression
- Outputs: `global_land_cover_YYYY.tif` files

#### Command to sync data

Command to upload land cover data from the output folder to S3.

```bash
uv run aws s3 sync lobal_land_cover/ s3://lcl-cogs/global-land-cover/ --exclude "*" --include "*.tif" --exclude "**/*.tif"
```

### merge_natural_lands.sh
Creates a global COG file from Natural Lands classification data.

**Usage:** `./merge_natural_lands.sh`

**What it does:**
- Downloads Natural Lands classification tiles from `gs://lcl_public/SBTN_NaturalLands/v1_1/classification`
- Creates a VRT file combining all tiles
- Converts to COG format with LZW compression
- Outputs: `natural_lands.tif`
