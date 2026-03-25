import asyncio
from typing import Any, Dict

import httpx
from pydantic import BaseModel

from src.agent.tools.data_handlers.base import (
    DataPullResult,
    DataSourceHandler,
)
from src.agent.tools.datasets_config import DATASETS
from src.shared.geocoding_helpers import (
    format_id,
    get_geometry_data,
)
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class BooleanResponse(BaseModel):
    """Response model for boolean queries"""

    result: bool


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

    BASE_URL = "https://analytics.globalnaturewatch.org"

    HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    def can_handle(self, dataset: Any) -> bool:
        """Check if this handler can process the given dataset"""
        dataset_id = dataset.get("dataset_id")
        full_ds = next(
            (ds for ds in DATASETS if ds["dataset_id"] == dataset_id), None
        )
        return full_ds is not None and bool(
            full_ds.get("analytics_api_endpoint")
        )

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
            # in https://analytics.globalnaturewatch.org/docs
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
        dataset: dict,
        aois: list[dict],
        start_date: str,
        end_date: str,
    ) -> Dict:
        """Build the API payload based on dataset type"""
        # Base payload structure common to all endpoints
        aoi_type = self._get_aoi_type(aois[0])
        # Fix for GADM IDs which come with a _1 suffix
        for aoi in aois:
            if aoi["src_id"][-2:] in ["_1", "_2", "_3", "_4", "_5"]:
                aoi["src_id"] = aoi["src_id"][:-2]

        # Handle custom areas differently - they need a feature collection
        if aoi_type["type"] == "feature_collection":
            features = []
            for aoi in aois:
                geometry_data = await get_geometry_data(
                    "custom", aoi["src_id"]
                )
                if not geometry_data:
                    raise ValueError(f"Custom area not found: {aoi['src_id']}")
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geometry_data["geometry"],
                        "properties": {
                            "name": geometry_data["name"],
                            "id": geometry_data["src_id"],
                        },
                    }
                )

            feature_collection = {
                "type": "FeatureCollection",
                "features": features,
            }

            base_payload = {
                "aoi": {
                    "type": aoi_type["type"],
                    "feature_collection": feature_collection,
                }
            }
        else:
            aoi_ids = [format_id(aoi["src_id"]) for aoi in aois]
            base_payload = {
                "aoi": {
                    "type": aoi_type["type"],
                    "ids": aoi_ids,
                }
            }

        logger.debug(f"dataset: {dataset}")

        config = dataset.get("analytics_config", {})
        payload = dict(base_payload)

        date_cfg = config.get("date_params", {})
        date_type = date_cfg.get("type", "none")

        if date_type == "date":
            payload[date_cfg["start_key"]] = start_date
            payload[date_cfg["end_key"]] = end_date
        elif date_type == "year":
            payload[date_cfg["start_key"]] = start_date[:4]
            payload[date_cfg["end_key"]] = end_date[:4]
        elif date_type == "year_5yr_interval":
            start_year = int(start_date[:4]) - int(start_date[:4]) % 5
            end_year = int(end_date[:4]) - int(end_date[:4]) % 5
            if start_year == end_year:
                end_year += 5
            min_start = date_cfg.get("min_start", 0)
            min_end = date_cfg.get("min_end", 0)
            payload[date_cfg["start_key"]] = str(max(min_start, start_year))
            payload[date_cfg["end_key"]] = str(max(min_end, end_year))

        param_defs = config.get("params", {})
        selected_params = dataset.get("params", {})
        for param_name, param_def in param_defs.items():
            default = param_def.get("default")
            is_list = param_def.get("type") == "list"
            if default == "all" and is_list:
                default = list(param_def.get("values", []))
            value = selected_params.get(param_name, default)
            if value is not None:
                payload[param_name] = value

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
        aois: list[dict],
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
        aois_id_to_name = {
            format_id(item["src_id"]): item["name"].split(",")[0]
            for item in aois
        }
        raw_data["name"] = [aois_id_to_name[idx] for idx in raw_data["aoi_id"]]
        # Get analytics url from result
        analytics_url = result["data"]["link"]

        return raw_data, data_points_count, message_detail, analytics_url

    async def pull_data(
        self,
        query: str,
        dataset: dict,
        start_date: str,
        end_date: str,
        change_over_time_query: bool,
        aois: list[dict],
    ) -> DataPullResult:
        try:
            selected_params = dataset.get("params", {})

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
            if selected_params:
                dataset["params"] = selected_params

            aoi_restrictions = dataset.get("analytics_config", {}).get(
                "aoi_restrictions"
            )
            if aoi_restrictions:
                allowed = aoi_restrictions["allowed_subtypes"]
                if aois[0]["subtype"] not in allowed:
                    msg = (
                        f"Can not pull data for aoi {aois[0].get('name', '')}. "
                        f"Subtype {aois[0]['subtype']} not supported for "
                        f"{dataset.get('dataset_name', 'this dataset')} data: "
                        f"{aoi_restrictions['error_message']}"
                    )
                    return DataPullResult(
                        success=False,
                        data=None,
                        message=msg,
                        data_points_count=0,
                        analytics_api_url=None,
                    )

            # Get the appropriate endpoint URL
            alt_endpoints = dataset.get("analytics_config", {}).get(
                "alternate_endpoints", {}
            )
            if change_over_time_query and "change_over_time" in alt_endpoints:
                endpoint_url = (
                    self.BASE_URL + alt_endpoints["change_over_time"]
                )
            else:
                endpoint_url = self.BASE_URL + dataset.get(
                    "analytics_api_endpoint"
                )

            # Build the payload based on dataset type
            payload = await self._build_payload(
                dataset, aois, start_date, end_date
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
                    success=False,
                    data=None,
                    message=error_msg,
                    analytics_api_url=None,
                )

            # Check if status key exists before accessing it
            if "status" not in result:
                error_msg = f"Analytics API response missing 'status' key. Available keys: {list(result.keys())}, Full response: {result}"
                logger.error(error_msg)
                return DataPullResult(
                    success=False,
                    data=None,
                    message=error_msg,
                    analytics_api_url=None,
                )

            # Handle pending status with retry logic
            aoi_names = ", ".join([aoi["name"] for aoi in aois])
            if result["status"] == "pending":
                logger.info(
                    "Analytics request is pending, will retry with polling..."
                )
                result = await self._poll_for_completion(
                    endpoint_url, payload, max_retries=10
                )
                if isinstance(result, str):
                    error_msg = f"Failed to get completed result after polling for {aoi_names}. Reason: {result}"
                    logger.error(error_msg)
                    return DataPullResult(
                        success=False,
                        data=None,
                        message=error_msg,
                        data_points_count=0,
                        analytics_api_url=None,
                    )
                else:
                    (
                        raw_data,
                        data_points_count,
                        message_detail,
                        analytics_url,
                    ) = await self._process_response_data(result, aois)
                    return DataPullResult(
                        success=True,
                        data=raw_data,
                        message=f"Successfully pulled {dataset.get('dataset_name')} data from GFW Analytics for {aoi_names}. {message_detail}.",
                        data_points_count=data_points_count,
                        analytics_api_url=analytics_url,
                    )
            elif result["status"] in ["success", "saved"]:
                (
                    raw_data,
                    data_points_count,
                    message_detail,
                    analytics_url,
                ) = await self._process_response_data(result, aois)
                return DataPullResult(
                    success=True,
                    data=raw_data,
                    message=f"Successfully pulled {dataset.get('dataset_name')} data from GFW Analytics for {aoi_names}. {message_detail}.",
                    data_points_count=data_points_count,
                    analytics_api_url=analytics_url,
                )
            else:
                error_msg = f"Failed to pull {dataset.get('dataset_name')} data from GFW Analytics for {aoi_names} - URL: {endpoint_url}, payload: {payload}, response: {response.text}"
                logger.error(error_msg)
                return DataPullResult(
                    success=False,
                    data=None,
                    message=error_msg,
                    analytics_api_url=result.get("data", {}).get("link", None),
                    data_points_count=0,
                )

        except Exception as e:
            error_msg = f"Failed to pull {dataset.get('dataset_name')} data from Analytics API: {e}"
            logger.error(error_msg, exc_info=True)
            return DataPullResult(
                success=False,
                data=None,
                message=error_msg,
                analytics_api_url=None,
            )
