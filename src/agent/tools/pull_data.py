from typing import Annotated, Dict, Optional

import httpx
import structlog
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from src.agent.datasets.dates import revise_date_range
from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
from src.agent.datasets.handlers.base import DataPullResult
from src.agent.i18n import t
from src.agent.language import DEFAULT_LANGUAGE
from src.agent.tool_spec import ToolCategory, ToolSpec
from src.api.data_models import StatisticsOrm
from src.shared.database import get_session_from_pool
from src.shared.logging_config import get_logger
from src.shared.request_context import current_user_id

logger = get_logger(__name__)


async def fetch_statistics_from_url(source_url: str) -> dict:
    """Fetch raw result data from an analytics source URL.

    The analytics API returns JSON with shape
    ``{"data": {"result": {...}}}``.  Returns the inner ``result`` dict
    so callers never need to deal with the response envelope.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(source_url)
        response.raise_for_status()
        return response.json()["data"]["result"]


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
                    dataset=dataset,
                    start_date=start_date,
                    end_date=end_date,
                    change_over_time_query=change_over_time_query,
                    aois=aois,
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
    state: Annotated[Dict, InjectedState],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    change_over_time_query: bool = False,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Pull data for the selected AOIs and dataset between start_date and end_date (YYYY-MM-DD)."""
    language = state.get("language") or DEFAULT_LANGUAGE
    dataset = state["dataset"]
    aoi_names = [a["name"] for a in state["aoi_selection"]["aois"]]
    logger.info(
        f"PULL-DATA-TOOL: AOI: {aoi_names}, Dataset: {dataset.get('dataset_name', '')}, Start Date: {start_date}, End Date: {end_date}"
    )

    effective_start, effective_end, range_clamped = await revise_date_range(
        start_date,
        end_date,
        dataset["dataset_id"],
        dataset.get("context_layer"),
    )
    if (end_date is not None and end_date < effective_start) or (
        start_date is not None and start_date > effective_end
    ):
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        await t(
                            "pull_data.date_out_of_range",
                            language,
                            start_date=start_date,
                            end_date=end_date,
                            dataset_name=dataset["dataset_name"],
                            available_start=effective_start,
                            available_end=effective_end,
                        ),
                        tool_call_id=tool_call_id,
                        status="success",
                        response_metadata={"msg_type": "human_feedback"},
                    )
                ],
            },
        )

    tool_messages = []
    result = await data_pull_orchestrator.pull_data(
        query=query,
        dataset=dataset,
        start_date=effective_start,
        end_date=effective_end,
        change_over_time_query=change_over_time_query,
        aois=state["aoi_selection"]["aois"],
    )

    # Create tool message
    tool_messages.append(result.message)
    logger.debug(f"Pull data tool message: {result.message}")

    if not result.success:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        await t(
                            "pull_data.no_data",
                            language,
                            dataset_name=dataset["dataset_name"],
                        ),
                        tool_call_id=tool_call_id,
                        status="success",
                        response_metadata={"msg_type": "human_feedback"},
                    )
                ],
            },
        )

    if range_clamped:
        tool_messages.append(
            f"Date range was adjusted to the dataset's available range: {effective_start} to {effective_end} "
            f"(requested: {start_date} to {end_date}). Warn the user about this adjustment."
        )

    tool_message = ToolMessage(
        content="|".join(tool_messages) if tool_messages else "No data pulled",
        tool_call_id=tool_call_id,
    )

    raw = result.data if isinstance(result.data, dict) else {}
    aoi_id_to_name = dict(zip(raw.get("aoi_id", []), raw.get("name", [])))

    aois = state["aoi_selection"]["aois"]
    statistics = {
        "dataset_name": dataset["dataset_name"],
        "dataset_id": dataset.get("dataset_id"),
        "start_date": effective_start,
        "end_date": effective_end,
        "source_url": result.analytics_api_url,
        # ID-backed statistics keep state light; fetch data from source_url when needed.
        "data": {},
        "aoi_id_to_name": aoi_id_to_name,
        "aoi_names": [aoi["name"] for aoi in aois],
        # src_id is only unique per source, so sources are kept parallel to ids.
        "aoi_ids": [aoi["src_id"] for aoi in aois],
        "aoi_sources": [aoi["source"] for aoi in aois],
        "parameters": dataset.get("parameters"),
        "context_layer": dataset.get("context_layer"),
    }

    ctx = structlog.contextvars.get_contextvars()
    async with get_session_from_pool() as session:
        statistics_row = StatisticsOrm(
            user_id=current_user_id(),
            thread_id=ctx.get("thread_id"),
            dataset_name=statistics["dataset_name"],
            dataset_id=statistics["dataset_id"],
            start_date=statistics["start_date"],
            end_date=statistics["end_date"],
            source_url=statistics["source_url"],
            aoi_names=statistics["aoi_names"],
            aoi_ids=statistics["aoi_ids"],
            aoi_sources=statistics["aoi_sources"],
            parameters=statistics["parameters"],
            context_layer=statistics["context_layer"],
        )
        session.add(statistics_row)
        await session.flush()
        statistics["id"] = str(statistics_row.id)
        await session.commit()

    return Command(
        update={
            "statistics": [statistics],
            "start_date": effective_start,
            "end_date": effective_end,
            "messages": [tool_message],
        },
    )


SPEC = ToolSpec(
    tool=pull_data,
    category=ToolCategory.PRIMITIVE,
    prompt_fragment="- pull_data(query): fetch data for the AOI and dataset currently in state. Run pick_aoi and pick_dataset first.",
)
