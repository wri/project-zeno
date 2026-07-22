from dataclasses import dataclass, field
from typing import Mapping, Optional

from src.agent.datasets.dates import revise_date_range
from src.agent.datasets.handlers.base import DataPullResult, DataSourceHandler
from src.agent.subagents.analyst.charts import InsightChart
from src.api.services.charts import ChartGenerator, column_to_rows

# The default canopy density threshold the catalog YAMLs mandate for the
# canopy-parameterised datasets (tree cover loss/gain/extent, carbon flux).
DEFAULT_CANOPY_COVER = 30


@dataclass
class AnalyzeResult:
    data: DataPullResult
    charts: list[InsightChart] = field(default_factory=list)
    source_urls: Optional[list[str]] = None


class AnalyzeService:
    def __init__(
        self,
        handler: DataSourceHandler,
        generators: Mapping[int, ChartGenerator],
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
        # The frontend sends one global default range; clamp it to the
        # dataset's actual coverage (fixed-content datasets force their
        # full range) so e.g. integrated alerts is not queried from 2001.
        start_date, end_date, _ = await revise_date_range(
            start_date, end_date, dataset_id
        )

        result = await self._handler.pull_data(
            query="",
            # Parameters are set explicitly: the payload builder hydrates
            # the dataset from the catalog and takes max(values) of the
            # full canopy_cover list — 75% — when none are provided.
            # Datasets without a canopy parameter ignore this entry.
            dataset={
                "dataset_id": dataset_id,
                "parameters": [
                    {
                        "name": "canopy_cover",
                        "values": [DEFAULT_CANOPY_COVER],
                    }
                ],
            },
            start_date=start_date,
            end_date=end_date,
            change_over_time_query=False,
            aois=aois,
        )

        charts: list[InsightChart] = []
        if result.success and result.data:
            generator = self._generators.get(dataset_id)
            if generator is not None:
                charts = generator.generate(column_to_rows(result.data))

        source_urls = (
            [result.analytics_api_url] if result.analytics_api_url else None
        )
        return AnalyzeResult(
            data=result,
            charts=charts,
            source_urls=source_urls,
        )
