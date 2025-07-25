"""
Example data source handler to demonstrate how to extend the pull_data system.

This shows how to add support for a new data source by implementing the DataSourceHandler interface.
"""

from typing import Any, Dict

from src.tools.data_handlers.base import DataPullResult, DataSourceHandler
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class ExampleAPIHandler(DataSourceHandler):
    """Example handler for a hypothetical external API"""

    def can_handle(self, dataset: Any, table_name: str) -> bool:
        """Check if this handler can process the dataset"""
        # Example: handle datasets from "EXAMPLE_API" source
        return hasattr(dataset, "source") and dataset.source == "EXAMPLE_API"

    async def pull_data(
        self,
        query: str,
        aoi_name: str,
        dataset: Any,
        aoi: Dict,
        subregion: str,
        subtype: str,
    ) -> DataPullResult:
        """Pull data from the example API"""
        try:
            # Example implementation
            logger.info(f"Pulling data from Example API for {aoi_name}")

            # Here you would implement the actual API call logic
            # For demonstration, we'll return mock data
            mock_data = {
                "data": [
                    {
                        "location": aoi_name,
                        "value": 42,
                        "timestamp": "2024-01-01",
                    },
                    {
                        "location": aoi_name,
                        "value": 38,
                        "timestamp": "2024-01-02",
                    },
                ]
            }

            return DataPullResult(
                success=True,
                data=mock_data,
                message=f"Successfully pulled {len(mock_data['data'])} data points from Example API for {aoi_name}",
                data_points_count=len(mock_data["data"]),
            )

        except Exception as e:
            error_msg = f"Failed to pull data from Example API: {e}"
            logger.error(error_msg, exc_info=True)
            return DataPullResult(
                success=False, data={"data": []}, message=error_msg
            )


# To use this handler, you would add it to the DataPullOrchestrator:
# from src.tools.data_handlers.example_handler import ExampleAPIHandler
#
# # In DataPullOrchestrator.__init__():
# self.handlers = [
#     DistAlertHandler(),
#     StandardGFWHandler(),
#     ExampleAPIHandler(),  # Add new handler here
# ]
