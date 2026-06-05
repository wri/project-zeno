from dataclasses import dataclass
from typing import Any, Optional

from src.agent.datasets.handlers.analytics_handler import TREE_COVER_LOSS_ID
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler


@dataclass
class AnalyzeResult:
    data: DataPullResult
    charts: Optional[Any] = None
    source_urls: Optional[list[str]] = None


def _column_to_rows(data: dict) -> list[dict]:
    keys = list(data.keys())
    return [dict(zip(keys, values)) for values in zip(*data.values())]


def _tcl_charts(data: dict) -> list[dict]:
    rows = [r for r in _column_to_rows(data) if r.get("area_ha") != 0]
    return [
        {
            "id": "chart_0",
            "title": "Annual Tree Cover Loss",
            "type": "bar",
            "insight": "",
            "data": rows,
            "xAxis": "year",
            "yAxis": "area_ha",
        },
        {
            "id": "chart_1",
            "title": "Annual GHG Emissions from Tree Cover Loss",
            "type": "bar",
            "insight": "",
            "data": rows,
            "xAxis": "year",
            "yAxis": "emissions_MgCO2e",
        },
    ]


def get_charts(
    result: DataPullResult, dataset_id: int
) -> Optional[list[dict]]:
    if not result.success or not result.data:
        return None
    if dataset_id == TREE_COVER_LOSS_ID:
        return _tcl_charts(result.data)
    return None


class AnalyzeService:
    def __init__(self, handler: DataSourceHandler):
        self._handler = handler

    async def analyze(
        self,
        aois: list[dict],
        dataset_id: int,
        start_date: str,
        end_date: str,
    ) -> AnalyzeResult:
        result = await self._handler.pull_data(
            query="",
            dataset={"dataset_id": dataset_id},
            start_date=start_date,
            end_date=end_date,
            change_over_time_query=False,
            aois=aois,
        )
        source_urls = (
            [result.analytics_api_url] if result.analytics_api_url else None
        )
        return AnalyzeResult(
            data=result,
            charts=get_charts(result, dataset_id),
            source_urls=source_urls,
        )
