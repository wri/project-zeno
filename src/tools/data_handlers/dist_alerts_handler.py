from typing import Any, Dict, List

import requests

from src.tools.data_handlers.base import (
    DataPullResult,
    DataSourceHandler,
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class DistAlertHandler(DataSourceHandler):
    """Handler for DIST-ALERT data source"""

    DIST_ALERT_URL = "http://analytics-416617519.us-east-1.elb.amazonaws.com/v0/land_change/dist_alerts/analytics"

    def can_handle(self, dataset: Any, table_name: str) -> bool:
        return table_name == "DIST-ALERT"

    def pull_data(
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
            aoi_gadm_id = aoi["gadm_id"].split("_")[0]

            payload = {
                "aoi": {
                    "type": "admin",
                    "ids": [aoi_gadm_id],
                    "provider": "gadm",
                    "version": "4.1",
                },
                "start_date": start_date,
                "end_date": end_date,
                "intersections": (
                    [dataset["context_layer"]] if dataset["context_layer"] else []
                ),
            }

            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            # Debug logging for payload
            logger.info(f"DIST-ALERT API Request - URL: {self.DIST_ALERT_URL}")
            logger.info(f"DIST-ALERT API Request - Headers: {headers}")
            logger.info(f"DIST-ALERT API Request - Payload: {payload}")

            response = requests.post(self.DIST_ALERT_URL, headers=headers, json=payload)

            # Debug logging for response
            logger.info(
                f"DIST-ALERT API Response - Status Code: {response.status_code}"
            )
            logger.info(f"DIST-ALERT API Response - Headers: {dict(response.headers)}")
            logger.info(f"DIST-ALERT API Response - Raw Text: {response.text}")

            try:
                result = response.json()
                logger.info(f"DIST-ALERT API Response - Parsed JSON: {result}")
            except Exception as json_error:
                error_msg = f"Failed to parse JSON response from DIST-ALERT API. Status: {response.status_code}, Text: {response.text}, Error: {json_error}"
                logger.error(error_msg)
                return DataPullResult(success=False, data=[], message=error_msg)

            # Check if status key exists before accessing it
            if "status" not in result:
                error_msg = f"DIST-ALERT API response missing 'status' key. Available keys: {list(result.keys())}, Full response: {result}"
                logger.error(error_msg)
                return DataPullResult(success=False, data=[], message=error_msg)

            if "status" in result and (
                result["status"] == "success" or result["status"] == "saved"
            ):
                download_link = result["data"]["link"]
                data = requests.get(download_link).json()
                raw_data = data["data"]["result"]

                return DataPullResult(
                    success=True,
                    data=raw_data,
                    message=f"Successfully pulled data from GFW for {aoi_name}. Found {len(raw_data['value'])} alerts.",
                    data_points_count=len(raw_data["value"]),
                )
            else:
                error_msg = f"Failed to pull data from GFW for {aoi_name} - DIST_ALERT_URL: {self.DIST_ALERT_URL}, payload: {payload}, response: {response.text}"
                logger.error(error_msg)
                return DataPullResult(success=False, data=[], message=error_msg)

        except Exception as e:
            error_msg = f"Failed to pull DIST-ALERT data: {e}"
            logger.error(error_msg, exc_info=True)
            return DataPullResult(success=False, data=[], message=error_msg)
