from typing import Annotated, Dict, List

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.tools.data_handlers.analytics_handler import AnalyticsHandler
from src.tools.data_handlers.base import DataPullResult
from src.tools.datasets_config import DATASETS
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class DataPullOrchestrator:
    """Orchestrates data pulling using appropriate handlers"""

    def __init__(self):
        self.handlers = [
            AnalyticsHandler(),
        ]

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
        """Pull data using the appropriate handler"""

        # Find appropriate handler
        for handler in self.handlers:
            if handler.can_handle(dataset):
                return await handler.pull_data(
                    query=query,
                    aoi=aoi,
                    subregion_aois=subregion_aois,
                    subregion=subregion,
                    subtype=subtype,
                    dataset=dataset,
                    start_date=start_date,
                    end_date=end_date,
                )

        return DataPullResult(
            success=False,
            data={"data": []},
            message=f"No handler found for dataset: {dataset['dataset_name']}. Please ask for data from GFW datasets.",
        )


# Global orchestrator instance
data_pull_orchestrator = DataPullOrchestrator()


@tool("pull_data")
async def pull_data(
    query: str,
    start_date: str,
    end_date: str,
    aoi_names: List[str],
    dataset_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
    state: Annotated[Dict, InjectedState] = None,
) -> Command:
    """
    Pull data for the previously selected AOIs and dataset in a given time range.

    This tool retrieves data from the appropriate data source based on the selected area of interest
    and dataset for the specified time period. It uses specialized handlers to process different
    data types and sources.

    Args:
        query: User query providing context for the data pull
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        aoi_names: List of names of the area of interest
        dataset_name: Name of the dataset to pull from
    """
    logger.info(
        f"PULL-DATA-TOOL: AOI: {aoi_names}, Dataset: {dataset_name}, Start Date: {start_date}, End Date: {end_date}"
    )

    dataset = state["dataset"]
    current_raw_data = state.get("raw_data", {})

    if current_raw_data is None:
        current_raw_data = {}

    tool_messages = []
    for aoi in state["aoi_options"]:
        # Use orchestrator to pull data
        result = await data_pull_orchestrator.pull_data(
            query=query,
            dataset=dataset,
            start_date=start_date,
            end_date=end_date,
            **aoi,
        )

        # Create tool message
        tool_messages.append(result.message)
        logger.debug(f"Pull data tool message: {result.message}")

        # Determine raw data format for backward compatibility
        if (
            result.success
            and isinstance(result.data, dict)
            and "data" in result.data
        ):
            raw_data = result.data["data"]
        elif result.success:
            raw_data = result.data
        else:
            raw_data = None

        if raw_data is None:
            continue

        raw_data["dataset_name"] = dataset["dataset_name"]
        if "name" in aoi["aoi"]:
            raw_data["aoi_name"] = aoi["aoi"]["name"]
        else:
            # This handles the custom AOIs that might not have a name
            raw_data["aoi_name"] = aoi["aoi"]["src_id"]

        ds_original = [
            ds
            for ds in DATASETS
            if ds["dataset_id"] == dataset.get("dataset_id")
        ]
        if not ds_original:
            raise ValueError(f"Dataset not found: {dataset.get('dataset_id')}")
        ds_original = ds_original[0]

        if ds_original.get("content_date_fixed"):
            raw_data["start_date"] = ds_original.get("start_date")
            raw_data["end_date"] = ds_original.get("end_date")
        else:
            raw_data["start_date"] = max(
                start_date, ds_original.get("start_date", "1900-01-01")
            )
            raw_data["end_date"] = min(
                end_date, ds_original.get("end_date", "9999-12-31")
            )
        raw_data["source_url"] = result.analytics_api_url

        if aoi["aoi"]["src_id"] not in current_raw_data:
            current_raw_data[aoi["aoi"]["src_id"]] = {}
        current_raw_data[aoi["aoi"]["src_id"]][dataset["dataset_id"]] = (
            raw_data
        )

    tool_message = ToolMessage(
        content="|".join(tool_messages) if tool_messages else "No data pulled",
        tool_call_id=tool_call_id,
    )

    return Command(
        update={
            "raw_data": current_raw_data,
            "start_date": start_date,
            "end_date": end_date,
            "messages": [tool_message],
        },
    )
