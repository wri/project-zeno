import time
from typing import Awaitable, Callable, Optional
from uuid import UUID

from src.agent.subagents.analyst.charts import Insight
from src.api.services.analysis_inputs import named_areas, pulled_statistics
from src.api.services.analyze import AnalyzeService
from src.api.services.job import JobRepository, JobStatus
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


# Names of AOIs by (source, src_id); see fetch_aoi_names.
AoiNameLookup = Callable[
    [list[tuple[str, str]]], Awaitable[dict[tuple[str, str], str]]
]


# Writes the statistics row of a pull; see persist_statistics.
StatisticsWriter = Callable[..., Awaitable[str]]


class AnalysisJobRunner:
    def __init__(
        self,
        service: AnalyzeService,
        repo: JobRepository,
        aoi_names: AoiNameLookup,
        write_statistics: StatisticsWriter,
    ):
        self._service = service
        self._repo = repo
        self._aoi_names = aoi_names
        self._write_statistics = write_statistics

    async def run(
        self,
        job_id: UUID,
        user_id: str,
        aois: list[dict],
        dataset_id: int,
        start_date: str,
        end_date: str,
        thread_id: Optional[str] = None,
        language: Optional[str] = None,
        context_layer: Optional[str] = None,
        canopy_cover: Optional[int] = None,
    ) -> None:
        await self._repo.update_job_status(job_id, JobStatus.RUNNING)
        logger.info(
            "analysis_job_started",
            job_id=str(job_id),
            user_id=user_id,
            dataset_id=dataset_id,
            start_date=start_date,
            end_date=end_date,
        )

        # The handler strips the GADM suffix from the AOI dicts it is given,
        # so the areas are taken before the pull.
        requested = [(aoi["source"], aoi["src_id"]) for aoi in aois]

        started_at = time.perf_counter()
        try:
            result = await self._service.analyze(
                aois=aois,
                dataset_id=dataset_id,
                start_date=start_date,
                end_date=end_date,
                language=language,
                context_layer=context_layer,
                canopy_cover=canopy_cover,
            )
            duration_ms = round((time.perf_counter() - started_at) * 1000)

            if not result.data.success:
                await self._repo.update_job_status(job_id, JobStatus.FAILED)
                logger.error(
                    "analysis_job_failed",
                    severity="high",
                    job_id=str(job_id),
                    user_id=user_id,
                    duration_ms=duration_ms,
                    error_details=result.data.message,
                )
                return

            # Charts only, no narrative: this job doesn't run the LLM text
            # generation step.
            insight = Insight(charts=result.charts)
            # The request is the one pull. The service passes the dates
            # through unclamped, so they are the dates it pulled.
            statistics_id = await self._write_statistics(
                pulled_statistics(
                    result.data,
                    dataset_id=dataset_id,
                    areas=named_areas(
                        requested, await self._aoi_names(requested)
                    ),
                    start_date=start_date,
                    end_date=end_date,
                    context_layer=context_layer,
                    canopy_cover=canopy_cover,
                ),
                user_id=user_id,
                thread_id=thread_id,
            )

            await self._repo.create_insight_resource(
                job_id=job_id,
                user_id=user_id,
                thread_id=thread_id,
                insight=insight,
                statistics_ids=[statistics_id],
            )

            await self._repo.update_job_status(job_id, JobStatus.COMPLETED)
            logger.info(
                "analysis_job_completed",
                job_id=str(job_id),
                user_id=user_id,
                duration_ms=duration_ms,
            )
        except Exception:
            # Fire-and-forget BackgroundTask: an unhandled exception would leave
            # the job stuck in RUNNING, so mark it FAILED instead. (May leave an
            # InsightOrm row with no JobResource pointing at it — harmless dead
            # data, not something that blocks the job or future requests.)
            await self._repo.update_job_status(job_id, JobStatus.FAILED)
            logger.exception(
                "analysis_job_errored",
                severity="high",
                job_id=str(job_id),
                user_id=user_id,
            )
