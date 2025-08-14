from typing import Annotated, Dict, List

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.tools.data_handlers.analytics_handler import AnalyticsHandler
from src.tools.data_handlers.base import DataPullResult
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


@tool("pull-data")
async def pull_data(
    query: str,
    start_date: str,
    end_date: str,
    aoi_name: str,
    dataset_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId] = None,
    state: Annotated[Dict, InjectedState] = None,
) -> Command:
    """
    Pull data for a specific AOI and dataset in a given time range.

    This tool retrieves data from the appropriate data source based on the selected area of interest
    and dataset for the specified time period. It uses specialized handlers to process different
    data types and sources.

    Args:
        query: User query providing context for the data pull
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        aoi_name: Name of the area of interest
        dataset_name: Name of the dataset to pull from
    """
    logger.info(
        f"PULL-DATA-TOOL: AOI: {aoi_name}, Dataset: {dataset_name}, Start Date: {start_date}, End Date: {end_date}"
    )

    aoi = state["aoi"]
    subregion_aois = state["subregion_aois"]
    subregion = state["subregion"]
    subtype = state["subtype"]
    dataset = state["dataset"]

    # Use orchestrator to pull data
    result = await data_pull_orchestrator.pull_data(
        query=query,
        aoi=aoi,
        subregion_aois=subregion_aois,
        subregion=subregion,
        subtype=subtype,
        dataset=dataset,
        start_date=start_date,
        end_date=end_date,
    )

    # Create tool message
    tool_message = ToolMessage(
        content=result.message,
        tool_call_id=tool_call_id,
    )

    logger.debug(f"Pull data tool message: {tool_message}")

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

    return Command(
        update={
            "raw_data": raw_data,
            "start_date": start_date,
            "end_date": end_date,
            "messages": [tool_message],
        },
    )


if __name__ == "__main__":
    from src.tools.pick_dataset import DatasetInfo

    # Example usage for testing
    mock_state = {
        "messages": [
            {
                "role": "user",
                "content": "How much tree cover was lost in Odisha, India in 2020?",
            }
        ],
        "aoi": {"GID_1": "IND.26_1"},
        "subregion_aois": [],
        "subregion": None,
        "subtype": "state-province",
        "dataset": DatasetInfo(
            dataset_id=1,
            source="GFW",
            data_layer="Tree cover loss",
            context_layer="Tree cover",
            threshold=30,
        ).model_dump(),
    }

    user_query = mock_state["messages"][0]["content"]
    command = pull_data.func(
        query=user_query,
        aoi=mock_state["aoi"],
        subregion_aois=mock_state["subregion_aois"],
        subregion=mock_state["subregion"],
        subtype=mock_state["subtype"],
        dataset=mock_state["dataset"],
        start_date="2020-01-01",
        end_date="2020-12-31",
        tool_call_id="test-id",
    )

    logger.info("--- Generated Command ---")
    logger.info(command)
