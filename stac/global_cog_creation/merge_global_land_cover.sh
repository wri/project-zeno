#!/bin/bash

# Script to sync data from Google Cloud Storage bucket
# Bucket: lcl_tiles
# Path: LCL_landCover/v2/2015-2024

# Help function
show_help() {
    cat << EOF
Usage: $0 LOCAL_DIR [OPTIONS]

Download and process Global Land Cover data for years 2015-2024 from Google Cloud Storage.

ARGUMENTS:
    LOCAL_DIR           Local directory to store the data (required)

OPTIONS:
    -h, --help          Show this help message and exit

EXAMPLES:
    $0 /path/to/data/dir       # Use specified directory
    $0 --help                  # Show this help message

DESCRIPTION:
    This script downloads Global Land Cover data from the lcl_tiles bucket for each year
    from 2015 to 2024. For each year, it:
    1. Downloads all tiles for that year
    2. Creates a VRT file combining all tiles
    3. Converts to Cloud-Optimized GeoTIFF (COG) format
    4. Cleans up temporary files

    Output files will be named: global_land_cover_YYYY.tif (one for each year)

REQUIREMENTS:
    - uv (Python package manager)
    - gsutil (Google Cloud SDK)
    - gdal tools (gdalbuildvrt, gdal_translate)
EOF
}

# Parse command line arguments
LOCAL_DIR=""
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            echo "Error: Unknown option $1"
            show_help
            exit 1
            ;;
        *)
            if [[ -z "$LOCAL_DIR" ]]; then
                LOCAL_DIR="$1"
            else
                echo "Error: Multiple directories specified. Only one LOCAL_DIR is allowed."
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# Check if LOCAL_DIR is specified
if [[ -z "$LOCAL_DIR" ]]; then
    echo "Error: LOCAL_DIR is required. Please specify a directory to store the data."
    show_help
    exit 1
fi

# Set variables
LOCAL_DIR="$LOCAL_DIR"

# Change to the local directory
cd "$LOCAL_DIR"


# Loop through years 2015-2024
for YEAR in {2016..2024}; do
    echo "Processing year: $YEAR"

    # Create local directory if it doesn't exist
    mkdir -p "$YEAR"

    uv run gsutil -m rsync -r "gs://lcl_tiles/LCL_landCover/v2/$YEAR" "$YEAR"

    # Create vrt file with all the tiles
    uv run gdalbuildvrt \
      global_land_cover_$YEAR.vrt \
      $YEAR/*.tif

    # Convert the vrt to COG
    uv run gdal_translate \
      global_land_cover_$YEAR.vrt \
      global_land_cover_$YEAR.tif \
      -of COG \
      -co COMPRESS=LZW \
      -co INTERLEAVE=BAND \
      -co BIGTIFF=YES \
      -co NUM_THREADS=ALL_CPUS \
      --config GDAL_CACHEMAX=75% \
      --config GDAL_SWATH_SIZE=0

    # Remove local directory for year
    echo "Completed processing year: $YEAR"

done

echo "All years 2015 to 2024 have been processed"
