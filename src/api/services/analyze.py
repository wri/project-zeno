from dataclasses import dataclass, field
from typing import Optional, Sequence

from src.agent.datasets.dates import revise_date_range
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts import ChartGenerator, column_to_rows
from src.api.services.charts.curated import build_curated_charts


async def _chart_period(
    start_date: str, end_date: str, dataset_id: int
) -> tuple[str, str]:
    """The period the charts span: the request's, clamped to the dates the
    dataset covers, as the template builder clamps its own. A chart that
    gives every day a slot then starts where the data does: integrated
    alerts begin in December 2023, and the Analyses pane asks for 2001 to
    2025. A dataset outside the catalog keeps the request's period."""
    try:
        start, end, _ = await revise_date_range(
            start_date, end_date, dataset_id
        )
    except ValueError:
        return start_date, end_date
    return start, end


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
        language: Optional[str] = None,
        context_layer: Optional[str] = None,
        canopy_cover: Optional[int] = None,
    ) -> AnalyzeResult:
        # The same dataset fields the agent's pick_dataset sets: the handler
        # reads the forest filter and the canopy cover threshold from them.
        dataset: dict = {"dataset_id": dataset_id}
        if context_layer:
            dataset["context_layer"] = context_layer
        if canopy_cover is not None:
            dataset["parameters"] = [
                {"name": "canopy_cover", "values": [canopy_cover]}
            ]
        result = await self._handler.pull_data(
            query="",
            dataset=dataset,
            start_date=start_date,
            end_date=end_date,
            change_over_time_query=False,
            aois=aois,
        )

        charts: list[InsightChart] = []
        if result.success and result.data:
            charts = await build_curated_charts(
                dataset_id,
                column_to_rows(result.data),
                language,
                self._generators,
                period=await _chart_period(start_date, end_date, dataset_id),
            )

        source_urls = (
            [result.analytics_api_url] if result.analytics_api_url else None
        )
        return AnalyzeResult(
            data=result,
            charts=charts,
            source_urls=source_urls,
        )
