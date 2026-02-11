from typing import Annotated, Dict

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.tools.data_handlers.analytics_handler import AnalyticsHandler
from src.agent.tools.data_handlers.base import DataPullResult
from src.agent.tools.datasets_config import DATASETS
from src.shared.logging_config import get_logger

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
        dataset: Dict,
        start_date: str,
        end_date: str,
        change_over_time_query: bool,
        aois: list[dict],
    ) -> DataPullResult:
        """Pull data using the appropriate handler"""

        # Find appropriate handler
        for handler in self.handlers:
            if handler.can_handle(dataset):
                return await handler.pull_data(
                    query=query,
                    change_over_time_query=change_over_time_query,
                    aois=aois,
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
    change_over_time_query: bool,
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
        change_over_time_query: Whether the query is about change over time. If it is about composition or current status, return False. If it is about dynamics or change, return True.
    """
    dataset = state["dataset"]
    aoi_names = [a["name"] for a in state["aoi_selection"]["aois"]]
    logger.info(
        f"PULL-DATA-TOOL: AOI: {aoi_names}, Dataset: {dataset.get('dataset_name', '')}, Start Date: {start_date}, End Date: {end_date}"
    )

    tool_messages = []
    result = await data_pull_orchestrator.pull_data(
        query=query,
        dataset=dataset,
        start_date=start_date,
        end_date=end_date,
        change_over_time_query=change_over_time_query,
        aois=state["aoi_selection"]["aois"],
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
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"No data found for the selected AOIs and dataset {dataset['dataset_name']}.",
                        tool_call_id=tool_call_id,
                        status="success",
                        response_metadata={"msg_type": "human_feedback"},
                    )
                ],
            },
        )

    raw_data["dataset_name"] = dataset["dataset_name"]

    ds_original = [
        ds for ds in DATASETS if ds["dataset_id"] == dataset.get("dataset_id")
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

    tool_message = ToolMessage(
        content="|".join(tool_messages) if tool_messages else "No data pulled",
        tool_call_id=tool_call_id,
    )

    return Command(
        update={
            "statistics": [
                {
                    "dataset_name": dataset["dataset_name"],
                    "start_date": start_date,
                    "end_date": end_date,
                    "source_url": result.analytics_api_url,
                    "data": raw_data,
                    "aoi_names": [
                        aoi["name"] for aoi in state["aoi_selection"]["aois"]
                    ],
                }
            ],
            # TODO: This is deprecated, remove it in the future
            "start_date": start_date,
            "end_date": end_date,
            "messages": [tool_message],
        },
    )
