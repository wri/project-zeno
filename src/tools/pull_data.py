from typing import Dict, Any, Annotated

from langchain_core.tools import tool
from langchain_core.messages import ToolMessage
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.utils.logging_config import get_logger
from src.tools.data_handlers.base import DataPullResult, dataset_names
from src.tools.data_handlers.dist_alerts_handler import DistAlertHandler
from src.tools.data_handlers.gfw_sql_handler import GFWSQLHandler

logger = get_logger(__name__)

class DataPullOrchestrator:
    """Orchestrates data pulling using appropriate handlers"""
    
    def __init__(self):
        self.handlers = [
            DistAlertHandler(),
            GFWSQLHandler(),
        ]
    
    def pull_data(self, query: str, aoi_name: str, dataset: Any, aoi: Dict, 
                  subregion: str, subtype: str) -> DataPullResult:
        """Pull data using the appropriate handler"""
        if dataset.source != "GFW":
            return DataPullResult(
                success=False,
                data={'data': []},
                message=f"Dataset from {dataset.source} is not yet available. We're working on adding support for this dataset soon. Please come back later to the platform with this question."
            )
        
        table_name = dataset_names.get(dataset.data_layer)
        if not table_name:
            return DataPullResult(
                success=False,
                data={'data': []},
                message=f"Dataset {dataset.data_layer} is not yet available. We're working on adding support for this dataset soon. Please come back later to the platform with this question."
            )
        
        # Find appropriate handler
        for handler in self.handlers:
            if handler.can_handle(dataset, table_name):
                return handler.pull_data(query, aoi_name, dataset, aoi, subregion, subtype)
        
        return DataPullResult(
            success=False,
            data={'data': []},
            message=f"No handler found for dataset: {dataset.data_layer}. Please ask for data from GFW datasets."
        )

# Global orchestrator instance
data_pull_orchestrator = DataPullOrchestrator()

@tool("pull-data")
def pull_data(query: str, aoi_name: str, dataset_name: str, tool_call_id: Annotated[str, InjectedToolCallId] = None, state: Annotated[Dict, InjectedState] = None) -> Command:
    """
    Given a user query, an AOI & a dataset, pulls data from the dataset for the specific AOI.

    Args:
        query: User query
        aoi_name: Name of the AOI
        dataset_name: Name of the dataset
    """
    logger.info(f"PULL-DATA-TOOL: aoi_name: '{aoi_name}', dataset_name: '{dataset_name}'")

    aoi = state["aoi"]
    subregion_aois = state["subregion_aois"]
    subregion = state["subregion"]
    subtype = state["subtype"]
    dataset = state["dataset"]

    # Use orchestrator to pull data
    result = data_pull_orchestrator.pull_data(
        query=query,
        aoi_name=aoi_name,
        dataset=dataset,
        aoi=aoi,
        subregion=subregion,
        subtype=subtype
    )
    
    # Create tool message
    tool_message = ToolMessage(
        content=result.message,
        tool_call_id=tool_call_id,
    )

    logger.debug(f"Pull data tool message: {tool_message}")
    
    # Determine raw data format for backward compatibility
    if result.success and isinstance(result.data, dict) and 'data' in result.data:
        raw_data = result.data["data"]
    elif result.success:
        raw_data = result.data
    else:
        raw_data = []

    return Command(
        update={
            "raw_data": raw_data,
            "messages": [tool_message],
        },
    )

if __name__ == "__main__":
    from src.tools.pick_dataset import DatasetInfo, DateRange
    # Example usage for testing
    mock_state = {
        "messages": [{"role": "user", "content": "How much tree cover was lost in Odisha, India in 2020?"}],
        "aoi": {"GID_1": "IND.26_1"},
        "subregion_aois": [],
        "subregion": None,
        "subtype": "state-province",
        "dataset": DatasetInfo(dataset_id=1, source="GFW", data_layer="Tree cover loss", context_layer="Tree cover", daterange=DateRange(start_date="2020-01-01", end_date="2020-12-31"), threshold=30),
    }
    
    user_query = mock_state["messages"][0]["content"]
    command = pull_data.func(query=user_query, aoi_name="Odisha", dataset_name="Tree cover loss", state=mock_state, tool_call_id="test-id")
    
    logger.info("--- Generated Command ---")
    logger.info(command)
