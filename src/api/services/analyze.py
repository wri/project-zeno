from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts import ChartGenerator, column_to_rows


@dataclass
class AnalyzeResult:
    data: DataPullResult
    charts: list[InsightChart] = field(default_factory=list)
    source_urls: Optional[list[str]] = None


class AnalyzeService:
    def __init__(
        self,
        handler: DataSourceHandler,
        generators: Sequence[ChartGenerator],
    ):
        self._handler = handler
        self._generators = generators

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

        charts: list[InsightChart] = []
        if result.success and result.data:
            rows = column_to_rows(result.data)
            for gen in self._generators:
                if gen.can_handle(dataset_id):
                    charts = gen.generate(rows)
                    break

        source_urls = (
            [result.analytics_api_url] if result.analytics_api_url else None
        )
        return AnalyzeResult(
            data=result,
            charts=charts,
            source_urls=source_urls,
        )
