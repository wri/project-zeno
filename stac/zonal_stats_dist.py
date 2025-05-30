import dask
import dotenv
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from dask.diagnostics import ProgressBar
from pystac_client import Client
from rasterio.mask import mask
from shapely.geometry import mapping
from stackstac import stack

ProgressBar().register()

STAC_API_URL = "https://eoapi.zeno-staging.ds.io/stac"


dotenv.load_dotenv("stac/env/.env_localhost")

stac = Client.open(STAC_API_URL)

gadm = gpd.read_file("/Users/tam/Desktop/gadm_410-levels.gpkg", layer="ADM_3")

search = stac.search(
    collections=["natural-lands-map-v1-1", "dist-alerts"],
    intersects=gadm.geometry.iloc[0],
)
items = list(search.get_items())

print(f"Found {len(items)} items")

da = stack(
    items,
    bounds_latlon=gadm.geometry.iloc[0].bounds,
    snap_bounds=True,
    epsg=4326,
)


data = da.compute()


def compute_stats_for_area(area_geom, area_id, raster_path):
    """Compute statistics for a single admin area."""

    # Open the raster dataset
    with rasterio.open(raster_path) as src:
        # Create a geographic mask for the admin area
        try:
            masked_data, mask_transform = mask(
                src, [mapping(area_geom)], crop=True
            )
        except Exception as e:
            print(f"Error masking data for area {area_id}: {e}")
            return {
                "id": area_id,
                "min": None,
                "max": None,
                "mean": None,
                "std": None,
                "count": 0,
            }

        # Filter out nodata values
        nodata = src.nodata
        valid_data = (
            masked_data[0][masked_data[0] != nodata]
            if nodata is not None
            else masked_data[0]
        )

        # If we have no valid data points, return empty stats
        if len(valid_data) == 0:
            return {
                "id": area_id,
                "min": None,
                "max": None,
                "mean": None,
                "std": None,
                "count": 0,
            }

        # Compute basic statistics
        stats = {
            "id": area_id,
            "min": float(np.min(valid_data)),
            "max": float(np.max(valid_data)),
            "mean": float(np.mean(valid_data)),
            "std": float(np.std(valid_data)),
            "count": int(len(valid_data)),
        }

        return stats


# Read the geopackage containing admin boundaries
gadm = gpd.read_file("/Users/tam/Desktop/gadm_410-levels.gpkg", layer="ADM_4")


# Path to your Cloud Optimized GeoTIFF
cog_path = "/Users/tam/Desktop/umd_glad_dist_alerts_v20250503/default.tif"

# List to store delayed objects
delayed_results = []

# Create delayed objects for each admin area
for idx, row in gadm.iterrows():
    # Get the area ID and geometry
    area_id = row[gadm.index.name] if gadm.index.name else idx
    area_geom = row["geometry"]

    # Create a delayed task
    delayed_result = dask.delayed(compute_stats_for_area)(
        area_geom, area_id, cog_path
    )
    delayed_results.append(delayed_result)


# Show progress bar while computing
with ProgressBar():
    results = dask.compute(*delayed_results)


# Convert results to a DataFrame
stats_df = pd.DataFrame(results)

# Save the DataFrame to a Parquet file
stats_df.to_parquet("/Users/tam/Desktop/dist_gadm_zonal_stats.parquet")
