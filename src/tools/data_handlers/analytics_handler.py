import asyncio
from typing import Any, Dict, List

import httpx

from src.tools.data_handlers.base import (
    DataPullResult,
    DataSourceHandler,
)
from src.tools.pick_dataset import DATASETS
from src.utils.geocoding_helpers import (
    SUBREGION_TO_AOI_TYPE_MAPPING,
    format_id,
    get_geometry_data,
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

ADMIN_SUBTYPES = (
    "country",
    "state-province",
    "district-county",
    "municipality",
    "locality",
    "neighbourhood",
)

# Add dataset-specific parameters
DIST_ALERT_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"]
    == "Global all ecosystem disturbance alerts (DIST-ALERT)"
][0]
NATURAL_LANDS_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "SBTN Natural Lands Map"
][0]
LAND_COVER_CHANGE_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Global land cover"
][0]
GRASSLANDS_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Global natural/semi-natural grassland extent"
][0]
TREE_COVER_LOSS_ID = [
    ds["dataset_id"]
    for ds in DATASETS
    if ds["dataset_name"] == "Tree cover loss"
][0]


class AnalyticsHandler(DataSourceHandler):
    """Generalized handler for GFW Analytics API endpoints"""

    BASE_URL = "http://analytics-416617519.us-east-1.elb.amazonaws.com"

    HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    def can_handle(self, dataset: Any) -> bool:
        """Check if this handler can process the given dataset"""
        return dataset.get("dataset_id") in [
            DIST_ALERT_ID,
            NATURAL_LANDS_ID,
            LAND_COVER_CHANGE_ID,
            GRASSLANDS_ID,
            TREE_COVER_LOSS_ID,
        ]

    def _get_aoi_type(self, aoi: Dict) -> str:
        """Get the type of the AOI"""

        if aoi["subtype"] in ADMIN_SUBTYPES:
            aoi_type = "admin"
        elif aoi["subtype"] == "key-biodiversity-area":
            aoi_type = "key_biodiversity_area"
        elif aoi["subtype"] == "indigenous-and-community-land":
            aoi_type = "indigenous_land"
        elif aoi["subtype"] == "protected-area":
            aoi_type = "protected_area"
        elif aoi["subtype"] == "custom-area":
            # See DistAlertsAnalyticsIn schema
            # in http://analytics-416617519.us-east-1.elb.amazonaws.com/docs
            aoi_type = "feature_collection"
        else:
            raise ValueError(f"Unknown AOI subtype: {aoi['subtype']}")

        if aoi_type == "admin":
            return {
                "type": "admin",
                "provider": "gadm",
                "version": "4.1",
            }
        else:
            return {"type": aoi_type}

    async def _build_payload(
        self,
        dataset: Dict,
        aoi: Dict,
        start_date: str,
        end_date: str,
        subregion_aois: List[Dict],
        subregion: str,
    ) -> Dict:
        """Build the API payload based on dataset type"""
        # Base payload structure common to all endpoints
        aoi_type = self._get_aoi_type(aoi)
        # Fix for GADM IDs which come with a _1 suffix
        if aoi["src_id"][-2:] in ["_1", "_2", "_3", "_4", "_5"]:
            aoi["src_id"] = aoi["src_id"][:-2]

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
            # Handle subregion AOIs
            if subregion:
                subregion_ids = [
                    format_id(subregion_aoi["src_id"])
                    for subregion_aoi in subregion_aois
                ]
                base_payload = {
                    "aoi": {
                        "type": SUBREGION_TO_AOI_TYPE_MAPPING[subregion],
                        "ids": subregion_ids,
                    }
                }
            else:
                # Base payload structure for standard AOI types
                base_payload = {
                    "aoi": {
                        "ids": [aoi["src_id"]],
                        **aoi_type,
                    }
                }

        logger.debug(f"dataset: {dataset}")

        if dataset.get("dataset_id") == DIST_ALERT_ID:
            payload = {
                **base_payload,
                "start_date": start_date,
                "end_date": end_date,
                "intersections": (
                    [dataset["context_layer"]]
                    if dataset.get("context_layer")
                    else []
                ),
            }

        elif dataset.get("dataset_id") in [
            NATURAL_LANDS_ID,
            LAND_COVER_CHANGE_ID,
        ]:
            # Natural lands and grasslands don't require date ranges
            payload = base_payload

        elif dataset.get("dataset_id") == GRASSLANDS_ID:
            payload = {
                **base_payload,
                "start_year": start_date[:4],  # Extract year from YYYY-MM-DD
                "end_year": end_date[:4],
            }
        elif dataset.get("dataset_id") == TREE_COVER_LOSS_ID:
            payload = {
                **base_payload,
                "start_year": start_date[:4],  # Extract year from YYYY-MM-DD
                "end_year": end_date[:4],
                "canopy_cover": 30,  # Default canopy cover threshold
                "intersections": (
                    [dataset["context_layer"]]
                    if dataset.get("context_layer")
                    else []
                ),
            }
        else:
            raise ValueError(
                f"Unknown dataset ID: {dataset.get('dataset_id')}"
            )

        return payload

    async def _poll_for_completion(
        self,
        endpoint_url: str,
        payload: Dict,
        max_retries: int = 5,
        poll_interval: float = 0.5,
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
                logger.warning(
                    f"Poll attempt {attempt + 1} failed with error: {e}"
                )
                continue

        msg = f"Max polling attempts ({max_retries}) exceeded for {result.get('data', {}).get('link', 'unknown url')}"
        logger.warning(msg)
        return msg

    async def _process_response_data(
        self,
        result: Dict,
        subregion: str,
        subregion_aois: List[Dict],
        dataset: Dict,
    ) -> tuple[Any, int, str]:
        """Process the response data based on dataset type."""

        if "data" not in result:
            raise ValueError(f"Response missing 'data' key: {result}")

        data_section = result["data"]

        if "link" not in data_section:
            raise ValueError(
                f"Data response missing 'link' key: {data_section}"
            )

        download_link = data_section["link"]
        async with httpx.AsyncClient() as client:
            response = await client.get(download_link)
            data = response.json()

        if "data" not in data:
            raise ValueError(
                f"Response missing 'result' key in response: {data}"
            )
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

        # Enrich raw_data with names
        if subregion:
            subregion_aois_id_to_name = {
                format_id(item["src_id"]): item["name"].split(",")[0]
                for item in subregion_aois
            }
            # For tree cover loss, the API returns "id" as the key for the AOI IDs, for other datasets it returns "aoi_id"
            api_result_id = (
                "id"
                if dataset.get("dataset_name") == "Tree cover loss"
                else "aoi_id"
            )
            raw_data["name"] = [
                subregion_aois_id_to_name[idx]
                for idx in raw_data[api_result_id]
            ]

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
            context_layer = dataset.get("context_layer")

            dataset = [
                ds
                for ds in DATASETS
                if ds["dataset_id"] == dataset.get("dataset_id")
            ]
            if not dataset:
                raise ValueError(
                    f"Dataset not found: {dataset.get('dataset_id')}"
                )
            dataset = dataset[0]
            if context_layer:
                dataset["context_layer"] = context_layer

            # Get the appropriate endpoint URL
            endpoint_url = self.BASE_URL + dataset.get(
                "analytics_api_endpoint"
            )

            # Build the payload based on dataset type
            payload = await self._build_payload(
                dataset, aoi, start_date, end_date, subregion_aois, subregion
            )

            # Debug logging for payload
            logger.info(
                f"Analytics API Request - Dataset: {dataset.get('dataset_name')}"
            )
            logger.info(f"Analytics API Request - URL: {endpoint_url}")
            logger.info(f"Analytics API Request - Headers: {self.HEADERS}")
            logger.info(f"Analytics API Request - Payload: {payload}")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint_url, headers=self.HEADERS, json=payload
                )

            # Debug logging for response
            logger.info(
                f"Analytics API Response - Status Code: {response.status_code}"
            )
            logger.info(
                f"Analytics API Response - Headers: {dict(response.headers)}"
            )
            logger.info(f"Analytics API Response - Raw Text: {response.text}")

            try:
                result = response.json()
                logger.info(f"Analytics API Response - Parsed JSON: {result}")
            except Exception as json_error:
                error_msg = f"Failed to parse JSON response from Analytics API. Status: {response.status_code}, Text: {response.text}, Error: {json_error}"
                logger.error(error_msg)
                return DataPullResult(
                    success=False, data=[], message=error_msg
                )

            # Check if status key exists before accessing it
            if "status" not in result:
                error_msg = f"Analytics API response missing 'status' key. Available keys: {list(result.keys())}, Full response: {result}"
                logger.error(error_msg)
                return DataPullResult(
                    success=False, data=[], message=error_msg
                )

            # Handle pending status with retry logic
            if result["status"] == "pending":
                logger.info(
                    "Analytics request is pending, will retry with polling..."
                )
                result = await self._poll_for_completion(
                    endpoint_url, payload, max_retries=10
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
                else:
                    (
                        raw_data,
                        data_points_count,
                        message_detail,
                    ) = await self._process_response_data(
                        result, subregion, subregion_aois, dataset
                    )
                    return DataPullResult(
                        success=True,
                        data=raw_data,
                        message=f"Successfully pulled {dataset.get('dataset_name')} data from GFW Analytics for {aoi_name}. {message_detail}.",
                        data_points_count=data_points_count,
                    )
            elif result["status"] in ["success", "saved"]:
                (
                    raw_data,
                    data_points_count,
                    message_detail,
                ) = await self._process_response_data(
                    result, subregion, subregion_aois, dataset
                )
                return DataPullResult(
                    success=True,
                    data=raw_data,
                    message=f"Successfully pulled {dataset.get('dataset_name')} data from GFW Analytics for {aoi_name}. {message_detail}.",
                    data_points_count=data_points_count,
                )
            else:
                error_msg = f"Failed to pull {dataset.get('dataset_name')} data from GFW Analytics for {aoi_name} - URL: {endpoint_url}, payload: {payload}, response: {response.text}"
                logger.error(error_msg)
                return DataPullResult(
                    success=False, data=[], message=error_msg
                )

        except Exception as e:
            error_msg = f"Failed to pull {dataset.get('dataset_name')} data from Analytics API: {e}"
            logger.error(error_msg, exc_info=True)
            return DataPullResult(success=False, data=[], message=error_msg)
