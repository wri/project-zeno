import asyncio
from typing import Any, Dict, List

import httpx
import requests

from src.tools.data_handlers.base import (
    DATASET_NAMES,
    TN_DIST_ALERT,
    TN_GRASSLANDS,
    TN_LAND_COVER_CHANGE,
    TN_NATURAL_LANDS,
    TN_TCL,
    DataPullResult,
    DataSourceHandler,
)
from src.utils.logging_config import get_logger
from src.utils.geocoding_helpers import get_geometry_data

logger = get_logger(__name__)

ADMIN_SUBTYPES = (
    "country",
    "state-province",
    "district-county",
    "municipality",
    "locality",
    "neighbourhood",
)


class AnalyticsHandler(DataSourceHandler):
    """Generalized handler for GFW Analytics API endpoints"""

    BASE_URL = "http://analytics-416617519.us-east-1.elb.amazonaws.com"

    HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Mapping of dataset names to their API endpoints
    ENDPOINT_MAPPING = {
        TN_DIST_ALERT: "/v0/land_change/dist_alerts/analytics",
        TN_NATURAL_LANDS: "/v0/land_change/natural_lands/analytics",
        TN_GRASSLANDS: "/v0/land_change/grasslands/analytics",
        TN_TCL: "/v0/land_change/tree_cover_loss/analytics",
        TN_LAND_COVER_CHANGE: "/v0/land_change/land_cover_change/analytics",
    }

    def can_handle(self, dataset: Any, table_name: str) -> bool:
        """Check if this handler can process the given dataset"""
        return table_name in self.ENDPOINT_MAPPING

    def _get_endpoint_url(self, table_name: str) -> str:
        """Get the full endpoint URL for a given dataset"""
        endpoint_path = self.ENDPOINT_MAPPING.get(table_name)
        if not endpoint_path:
            raise ValueError(f"No endpoint mapping found for dataset: {table_name}")
        return f"{self.BASE_URL}{endpoint_path}"

    def _get_aoi_type(self, aoi: Dict) -> str:
        """Get the type of the AOI"""

        if aoi["subtype"] in ADMIN_SUBTYPES:
            return "admin"
        elif aoi["subtype"] == "key-biodiversity-area":
            return "key_biodiversity_area"
        elif aoi["subtype"] == "indigenous-and-community-land":
            return "indigenous_land"
        elif aoi["subtype"] == "protected-area":
            return "protected_area"
        # custom_area instead of custom-area because
        # that's what the existing
        if aoi["subtype"] == "custom-area":
            # See DistAlertsAnalyticsIn schema
            # in http://analytics-416617519.us-east-1.elb.amazonaws.com/docs
            return "feature_collection"
        else:
            raise ValueError(f"Unknown AOI subtype: {aoi['subtype']}")

    async def _build_payload(
        self, dataset: Dict, table_name: str, aoi: Dict, start_date: str, end_date: str
    ) -> Dict:
        """Build the API payload based on dataset type"""
        # Fix for GADM IDs which come with a _1 suffix
        if aoi["src_id"].endswith("_1"):
            aoi["src_id"] = aoi["src_id"][:-2]

        aoi_type = self._get_aoi_type(aoi)

        # Handle custom areas differently - they need a feature collection
        if aoi_type == "feature_collection":
            geometry_data = await get_geometry_data("custom", aoi["src_id"])
            if not geometry_data:
                raise ValueError(f"Custom area not found: {aoi['src_id']}")

            feature_collection = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": geometry_data["geometry"],
                        "properties": {
                            "name": geometry_data["name"],
                            "id": geometry_data["src_id"],
                        },
                    }
                ],
            }

            base_payload = {
                "aoi": {
                    "type": aoi_type,
                    "feature_collection": feature_collection,
                }
            }
        else:
            # Base payload structure for standard AOI types
            base_payload = {
                "aoi": {
                    "type": aoi_type,
                    "ids": [aoi["src_id"]],
                }
            }

        logger.info(f"dataset: {dataset}")

        # Add dataset-specific parameters
        if table_name == TN_DIST_ALERT:
            payload = {
                **base_payload,
                "start_date": start_date,
                "end_date": end_date,
                "intersections": (
                    [dataset["context_layer"]] if dataset.get("context_layer") else []
                ),
            }

        elif table_name in [TN_NATURAL_LANDS, TN_LAND_COVER_CHANGE]:
            # Natural lands and grasslands don't require date ranges
            payload = base_payload

        elif table_name == TN_GRASSLANDS:
            payload = {
                **base_payload,
                "start_year": start_date[:4],  # Extract year from YYYY-MM-DD
                "end_year": end_date[:4],
            }
        elif table_name == TN_TCL:
            payload = {
                **base_payload,
                "start_year": start_date[:4],  # Extract year from YYYY-MM-DD
                "end_year": end_date[:4],
                "canopy_cover": 30,  # Default canopy cover threshold
                "intersections": (
                    [dataset["context_layer"]] if dataset.get("context_layer") else []
                ),
            }
        else:
            raise ValueError(f"Unknown table name: {table_name}")

        return payload

    async def _poll_for_completion(
        self,
        endpoint_url: str,
        payload: Dict,
        max_retries: int = 5,
        poll_interval: float = 1,
    ) -> Dict | str:
        """Poll the API until the request is completed or max retries exceeded."""
        for attempt in range(max_retries):
            logger.info(f"Polling attempt {attempt + 1}/{max_retries}")
            await asyncio.sleep(poll_interval * (attempt + 1))

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        endpoint_url, headers=self.HEADERS, json=payload
                    )
                if response.status_code >= 400:
                    logger.warning(
                        f"Poll attempt {attempt + 1} failed with status {response.status_code}"
                    )
                    continue

                result = response.json()
                status = result.get("status")
                logger.info(
                    f"Poll attempt {attempt + 1}, Status = {status}, Message = {result.get('message')}"
                )

                if status in ["success", "saved"]:
                    logger.info(
                        f"Request completed successfully after {attempt + 1} polling attempts"
                    )
                    return result
                elif status in ["failed", "error"]:
                    msg = f"Request failed with status: {status}"
                    logger.error(msg)
                    return msg

            except Exception as e:
                logger.warning(f"Poll attempt {attempt + 1} failed with error: {e}")
                continue

        msg = f"Max polling attempts ({max_retries}) exceeded for {result.get('data', {}).get('link', 'unknown url')}"
        logger.warning(msg)
        return msg

    def _process_response_data(
        self, result: Dict, table_name: str
    ) -> tuple[Any, int, str]:
        """Process the response data based on dataset type"""
        if "data" not in result:
            raise ValueError(f"Response missing 'data' key: {result}")

        data_section = result["data"]

        if "link" not in data_section:
            raise ValueError(f"Data response missing 'link' key: {data_section}")

        download_link = data_section["link"]
        data = requests.get(download_link).json()

        if "data" not in data:
            raise ValueError(f"Response missing 'result' key in response: {data}")
        if "result" not in data["data"]:
            raise ValueError(
                f"Response missing 'result' key in data section: {data['data']}"
            )

        raw_data = data["data"]["result"]

        # Count data points based on available arrays in the result
        data_points_count = 0
        if isinstance(raw_data, dict):
            # Find the first array in the result to count data points
            for key, value in raw_data.items():
                if isinstance(value, list):
                    data_points_count = len(value)
                    break

        message_detail = f"Found {data_points_count} data points"

        return raw_data, data_points_count, message_detail

    async def pull_data(
        self,
        query: str,
        aoi: Dict,
        subregion_aois: List[Dict],
        subregion: str,
        subtype: str,
        dataset: Dict,
        start_date: str,
        end_date: str,
    ) -> DataPullResult:
        try:
            aoi_name = aoi["name"]
            table_name = dataset.get("table_name") or DATASET_NAMES.get(
                dataset.get("dataset_name")
            )

            if not table_name:
                error_msg = f"No table_name or data_layer found in dataset: {dataset}"
                logger.error(error_msg)
                return DataPullResult(success=False, data=[], message=error_msg)

            # Get the appropriate endpoint URL
            endpoint_url = self._get_endpoint_url(table_name)

            logger.debug(f"Endpoint URL: {endpoint_url}")

            # Build the payload based on dataset type
            payload = await self._build_payload(
                dataset, table_name, aoi, start_date, end_date
            )

            # Debug logging for payload
            logger.info(f"Analytics API Request - Dataset: {table_name}")
            logger.info(f"Analytics API Request - URL: {endpoint_url}")
            logger.info(f"Analytics API Request - Headers: {self.HEADERS}")
            logger.info(f"Analytics API Request - Payload: {payload}")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint_url, headers=self.HEADERS, json=payload
                )

            # Debug logging for response
            logger.info(f"Analytics API Response - Status Code: {response.status_code}")
            logger.info(f"Analytics API Response - Headers: {dict(response.headers)}")
            logger.info(f"Analytics API Response - Raw Text: {response.text}")

            try:
                result = response.json()
                logger.info(f"Analytics API Response - Parsed JSON: {result}")
            except Exception as json_error:
                error_msg = f"Failed to parse JSON response from Analytics API. Status: {response.status_code}, Text: {response.text}, Error: {json_error}"
                logger.error(error_msg)
                return DataPullResult(success=False, data=[], message=error_msg)

            # Check if status key exists before accessing it
            if "status" not in result:
                error_msg = f"Analytics API response missing 'status' key. Available keys: {list(result.keys())}, Full response: {result}"
                logger.error(error_msg)
                return DataPullResult(success=False, data=[], message=error_msg)

            # Handle pending status with retry logic
            if result["status"] == "pending":
                logger.info("Analytics request is pending, will retry with polling...")
                result = await self._poll_for_completion(
                    endpoint_url, payload, max_retries=5, poll_interval=1
                )
                if isinstance(result, str):
                    error_msg = f"Failed to get completed result after polling for {aoi_name}. Reason: {result}"
                    logger.error(error_msg)
                    return DataPullResult(
                        success=False,
                        data=[],
                        message=error_msg,
                        data_points_count=0,
                    )

            if "status" in result and result["status"] in ["success", "saved"]:
                raw_data, data_points_count, message_detail = (
                    self._process_response_data(result, table_name)
                )

                return DataPullResult(
                    success=True,
                    data=raw_data,
                    message=f"Successfully pulled {table_name} data from GFW Analytics for {aoi_name}. {message_detail}.",
                    data_points_count=data_points_count,
                )
            else:
                error_msg = f"Failed to pull {table_name} data from GFW Analytics for {aoi_name} - URL: {endpoint_url}, payload: {payload}, response: {response.text}"
                logger.error(error_msg)
                return DataPullResult(success=False, data=[], message=error_msg)

        except Exception as e:
            error_msg = f"Failed to pull {table_name} data from Analytics API: {e}"
            logger.error(error_msg, exc_info=True)
            return DataPullResult(success=False, data=[], message=error_msg)
