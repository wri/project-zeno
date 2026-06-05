from dataclasses import dataclass
from typing import Any, Optional

from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler


@dataclass
class AnalyzeResult:
    data: DataPullResult
    charts: Optional[Any] = None


def get_charts(result: DataPullResult):
    raise NotImplementedError


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
        return AnalyzeResult(data=result, charts=get_charts(result))
