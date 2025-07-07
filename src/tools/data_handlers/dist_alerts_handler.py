from typing import Any, Dict

import requests

from src.tools.data_handlers.base import (
    DataPullResult,
    DataSourceHandler,
    gadm_levels,
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class DistAlertHandler(DataSourceHandler):
    """Handler for DIST-ALERT data source"""

    DIST_ALERT_URL = "http://zeno-a-publi-zrfwjzqkhk5t-237896174.us-east-1.elb.amazonaws.com/v0/land_change/dist_alerts/analytics"

    def can_handle(self, dataset: Any, table_name: str) -> bool:
        return table_name == "DIST-ALERT"

    def pull_data(
        self,
        query: str,
        aoi_name: str,
        dataset: Any,
        aoi: Dict,
        subregion: str,
        subtype: str,
    ) -> DataPullResult:
        try:
            gadm_level = gadm_levels[subtype]
            aoi_gadm_id = aoi[gadm_level["col_name"]].split("_")[0]

            payload = {
                "aois": [
                    {
                        "type": "admin",
                        "id": aoi_gadm_id,
                        "provider": "gadm",
                        "version": "4.1",
                    }
                ],
                "start_date": dataset.daterange.start_date,
                "end_date": dataset.daterange.end_date,
                "intersections": [dataset.context_layer]
                if dataset.context_layer
                else [],
            }

            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            response = requests.post(
                self.DIST_ALERT_URL, headers=headers, json=payload
            )
            response.raise_for_status()

            result = response.json()

            if result["status"] == "success":
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
                return DataPullResult(
                    success=False, data=[], message=error_msg
                )

        except Exception as e:
            error_msg = f"Failed to pull DIST-ALERT data: {e}"
            logger.error(error_msg, exc_info=True)
            return DataPullResult(success=False, data=[], message=error_msg)
