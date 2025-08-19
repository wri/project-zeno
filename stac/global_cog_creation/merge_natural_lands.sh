uv run gsutil -m rsync -r "gs://lcl_public/SBTN_NaturalLands/v1_1/classification" SBTN_NaturalLands_classification/classification

# Create vrt file with all the tiles
uv run gdalbuildvrt \
SBTN_NaturalLands_classification/natural_lands.vrt \
SBTN_NaturalLands_classification/classification/*.tif
# Convert the vrt to COG
uv run gdal_translate \
  SBTN_NaturalLands_classification/natural_lands.vrt \
  SBTN_NaturalLands_classification/natural_lands.tif \
  -of COG \
  -co COMPRESS=LZW \
  -co INTERLEAVE=BAND \
  -co BIGTIFF=YES \
  -co NUM_THREADS=ALL_CPUS \
  --config GDAL_CACHEMAX=75% \
  --config GDAL_SWATH_SIZE=0
