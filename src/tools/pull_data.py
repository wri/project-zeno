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


def get_aois_to_pull(
    aoi_options: List[Dict], dataset_id: str, previous_pulls: Dict
) -> List[Dict]:
    """Check previous pulls for a given dataset"""
    return [
        aoi
        for aoi in aoi_options
        if (aoi["src_id"], dataset_id) not in previous_pulls
    ]


@tool("pull-data")
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

    subregion_aois = state["subregion_aois"]
    subregion = state["subregion"]
    subtype = state["subtype"]
    dataset = state["dataset"]
    current_raw_data = state.get("raw_data", {})

    # Fuzzy match from aoi available in state, match by ID from all available aois, ingnore input.
    aois_to_pull = get_aois_to_pull(
        state["aoi_options"], dataset["dataset_id"], current_raw_data
    )
    if not aois_to_pull:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="No new AOIs to pull data for. All requested data has already been retrieved.",
                        tool_call_id=tool_call_id,
                    )
                ],
            },
        )

    if current_raw_data is None:
        current_raw_data = {}

    tool_messages = []
    for aoi in aois_to_pull:
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
        tool_messages.append(tool_message)

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

        if raw_data is not None:
            raw_data["dataset_name"] = dataset["dataset_name"]
            if "name" in aoi:
                raw_data["aoi_name"] = aoi["name"]
            else:
                # This handles the custom AOIs that might not have a name
                raw_data["aoi_name"] = aoi["src_id"]

        current_raw_data.update(
            {(aoi["src_id"], dataset["dataset_id"]): raw_data}
        )

    return Command(
        update={
            "raw_data": current_raw_data,
            "start_date": start_date,
            "end_date": end_date,
            "messages": tool_messages,
        },
    )
