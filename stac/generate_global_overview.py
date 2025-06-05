#!/usr/bin/env python3
"""
STAC COG Overview Mosaic Creator

This script fetches a STAC collection, extracts overviews from each COG,
and stitches them together into a single mosaic file for visualization.
"""

import logging
import os
import tempfile
from typing import List, Optional, Tuple

import dotenv
import numpy as np
import rasterio
import requests
from rasterio.crs import CRS
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject

dotenv.load_dotenv("stac/env/.env_localhost")

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class STACCOGMosaicCreator:
    """Creates mosaics from STAC collection COG overviews."""

    def __init__(
        self,
        stac_collection_url: str,
        overview_level: int = -3,
        max_items: Optional[int] = None,
    ):
        """
        Initialize the mosaic creator.

        Args:
            stac_collection_url: URL to the STAC collection
            overview_level: Which overview level to use (-1 for smallest/highest level)
            max_items: Optional limit on number of items to process (for testing)
        """
        self.stac_collection_url = stac_collection_url
        self.overview_level = overview_level
        self.max_items = max_items
        self.items = []

    def fetch_stac_items(self) -> List[dict]:
        """Fetch all items from the STAC collection."""
        logger.info(
            f"Fetching STAC collection from {self.stac_collection_url}"
        )

        # Parse the collection URL to get the items endpoint
        if "/collections/" in self.stac_collection_url:
            items_url = f"{self.stac_collection_url}/items"
        else:
            raise ValueError("Invalid STAC collection URL format")

        try:
            # Fetch items with pagination
            all_items = []
            next_url = items_url

            while next_url:
                response = requests.get(next_url)
                response.raise_for_status()
                data = response.json()

                # Get next page link before processing items
                next_link = None
                for link in data.get("links", []):
                    if link.get("rel") == "next":
                        next_link = link.get("href")
                        break

                # Add items up to max_items limit
                remaining = (
                    None
                    if self.max_items is None
                    else self.max_items - len(all_items)
                )
                new_items = data.get("features", [])[:remaining]
                all_items.extend(new_items)

                logger.info(f"Fetched {len(all_items)} items so far...")

                # Update next_url and check if we should continue
                next_url = next_link
                if (
                    self.max_items is not None
                    and len(all_items) >= self.max_items
                ):
                    logger.info(f"Reached max items limit of {self.max_items}")
                    break
                elif not next_link:
                    logger.info("Reached last page of STAC catalog")
                    break

            logger.info(f"Total items fetched: {len(all_items)}")
            self.items = all_items
            return all_items

        except requests.RequestException as e:
            logger.error(f"Failed to fetch STAC items: {e}")
            raise

    def get_cog_urls(self) -> List[str]:
        """Extract COG URLs from STAC items."""
        cog_urls = []

        for item in self.items:
            # Look for COG assets - common keys are 'data', 'cog', 'image', etc.
            assets = item.get("assets", {})

            # Try common asset keys
            cog_asset = None
            for key in ["data", "cog", "image", "visual", "default"]:
                if key in assets:
                    asset = assets[key]
                    # Check if it's a COG (GeoTIFF)
                    media_type = asset.get("type", "").lower()
                    if "geotiff" in media_type or "tiff" in media_type:
                        cog_asset = asset
                        break

            # If no specific key found, take the first GeoTIFF asset
            if not cog_asset:
                for asset in assets.values():
                    media_type = asset.get("type", "").lower()
                    if "geotiff" in media_type or "tiff" in media_type:
                        cog_asset = asset
                        break

            if cog_asset and "href" in cog_asset:
                cog_urls.append(cog_asset["href"])

        logger.info(f"Found {len(cog_urls)} COG URLs")
        return cog_urls

    def read_cog_overview(
        self, cog_url: str
    ) -> Optional[Tuple[np.ndarray, dict]]:
        """
        Read a specific overview level from a COG.

        Args:
            cog_url: URL to the COG file

        Returns:
            Tuple of (data_array, profile) or None if failed
        """
        try:
            with rasterio.open(cog_url) as src:
                # Get available overviews
                overviews = src.overviews(1)

                if not overviews:
                    logger.warning(f"No overviews found in {cog_url}")
                    # Use the original resolution but decimated
                    overview_factor = 16  # Adjust as needed
                    height = max(1, src.height // overview_factor)
                    width = max(1, src.width // overview_factor)
                    data = src.read(1, out_shape=(height, width))
                else:
                    # Use specified overview level
                    if self.overview_level == -1:
                        overview_factor = overviews[-1]  # Smallest overview
                    else:
                        overview_factor = overviews[
                            min(self.overview_level, len(overviews) - 1)
                        ]

                    # Read the overview
                    height = max(1, src.height // overview_factor)
                    width = max(1, src.width // overview_factor)
                    data = src.read(1, out_shape=(height, width))

                # Create profile for the overview
                profile = src.profile.copy()
                profile.update(
                    {
                        "height": data.shape[0],
                        "width": data.shape[1],
                        "transform": src.transform
                        * src.transform.scale(
                            src.width / data.shape[1],
                            src.height / data.shape[0],
                        ),
                    }
                )

                return data, profile

        except Exception as e:
            logger.error(f"Failed to read overview from {cog_url}: {e}")
            return None

    def create_mosaic(
        self, output_path: str, target_crs: str = "EPSG:4326"
    ) -> str:
        """
        Create a mosaic from all COG overviews.

        Args:
            output_path: Path where to save the mosaic
            target_crs: Target CRS for the mosaic

        Returns:
            Path to the created mosaic file
        """
        if not self.items:
            self.fetch_stac_items()

        cog_urls = self.get_cog_urls()

        if not cog_urls:
            raise ValueError("No COG URLs found in the STAC collection")

        logger.info(f"Creating mosaic from {len(cog_urls)} COGs...")

        # Create temporary files for reprojected overviews
        temp_files = []
        successful_files = []

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Process each COG
                for i, cog_url in enumerate(cog_urls):
                    logger.info(
                        f"Processing COG {i+1}/{len(cog_urls)}: {cog_url}"
                    )

                    overview_data = self.read_cog_overview(cog_url)
                    if overview_data is None:
                        continue

                    data, profile = overview_data

                    # Reproject to target CRS if needed
                    if profile["crs"] != CRS.from_string(target_crs):
                        temp_file = os.path.join(temp_dir, f"overview_{i}.tif")

                        # Calculate transform for reprojection
                        dst_crs = CRS.from_string(target_crs)
                        transform, width, height = calculate_default_transform(
                            profile["crs"],
                            dst_crs,
                            profile["width"],
                            profile["height"],
                            *rasterio.transform.array_bounds(
                                profile["height"],
                                profile["width"],
                                profile["transform"],
                            ),
                        )

                        # Create destination array
                        dst_data = np.empty((height, width), dtype=data.dtype)

                        # Reproject
                        reproject(
                            source=data,
                            destination=dst_data,
                            src_transform=profile["transform"],
                            src_crs=profile["crs"],
                            dst_transform=transform,
                            dst_crs=dst_crs,
                            resampling=Resampling.nearest,
                        )

                        # Save reprojected overview
                        profile.update(
                            {
                                "crs": dst_crs,
                                "transform": transform,
                                "width": width,
                                "height": height,
                            }
                        )

                        with rasterio.open(temp_file, "w", **profile) as dst:
                            dst.write(dst_data, 1)
                    else:
                        # Save overview as-is
                        temp_file = os.path.join(temp_dir, f"overview_{i}.tif")
                        with rasterio.open(temp_file, "w", **profile) as dst:
                            dst.write(data, 1)

                    temp_files.append(temp_file)
                    successful_files.append(temp_file)

                if not successful_files:
                    raise ValueError("No valid overviews could be processed")

                logger.info(
                    f"Successfully processed {len(successful_files)} overviews"
                )

                # Open all files for mosaicking
                src_files_to_mosaic = []
                for file_path in successful_files:
                    src = rasterio.open(file_path)
                    src_files_to_mosaic.append(src)

                # Create mosaic
                logger.info("Creating mosaic...")
                mosaic, out_trans = merge(src_files_to_mosaic)

                # Update profile for output
                out_profile = src_files_to_mosaic[0].profile.copy()
                out_profile.update(
                    {
                        "driver": "GTiff",
                        "height": mosaic.shape[1],
                        "width": mosaic.shape[2],
                        "transform": out_trans,
                        "crs": target_crs,
                        "compress": "lzw",
                        "tiled": True,
                        "blockxsize": 512,
                        "blockysize": 512,
                    }
                )

                # Write mosaic
                with rasterio.open(output_path, "w", **out_profile) as dest:
                    dest.write(mosaic)

                # Close source files
                for src in src_files_to_mosaic:
                    src.close()

                logger.info(f"Mosaic created successfully: {output_path}")
                return output_path

        except Exception as e:
            logger.error(f"Failed to create mosaic: {e}")
            raise


def main():
    """Main function to demonstrate usage."""

    # Configuration
    stac_collection_url = "https://eoapi.zeno-staging.ds.io/stac/collections/natural-lands-map-v1-1"
    output_path = "natural_lands_mosaic_overview_merged.tif"

    # Create mosaic creator with test settings
    creator = STACCOGMosaicCreator(
        stac_collection_url=stac_collection_url,
        overview_level=-1,  # Use the smallest overview
        # max_items=50  # Limit to first 10 items for testing
        max_items=None,  # Limit to first 10 items for testing
    )

    try:
        # Create the mosaic
        mosaic_path = creator.create_mosaic(
            output_path=output_path,
            target_crs="EPSG:4326",  # Web Mercator for web visualization
        )

        print(f"✅ Mosaic created successfully: {mosaic_path}")
        print(f"📝 Processed {len(creator.items)} items")

        # Print some info about the created mosaic
        with rasterio.open(mosaic_path) as src:
            print("📊 Mosaic Info:")
            print(f"   Dimensions: {src.width} x {src.height}")
            print(f"   CRS: {src.crs}")
            print(f"   Bounds: {src.bounds}")
            print(f"   Data type: {src.dtypes[0]}")

    except Exception as e:
        print(f"❌ Failed to create mosaic: {e}")


if __name__ == "__main__":
    main()
