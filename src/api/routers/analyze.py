"""Analysis job endpoint."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
)
from src.api.auth.dependencies import require_auth
from src.api.repositories.job_repository import get_job_repository
from src.api.schemas import AnalyzeRequest, JobResponse, UserModel
from src.api.services.analysis_job import AnalysisJobRunner
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import TCLChartGenerator
from src.api.services.job import JobRepository, JobType

router = APIRouter()

handler = AnalyticsHandler()
generators = [TCLChartGenerator(TREE_COVER_LOSS_ID)]


def get_analysis_runner(
    repo: JobRepository = Depends(get_job_repository),
) -> AnalysisJobRunner:
    return AnalysisJobRunner(
        service=AnalyzeService(handler, generators),
        repo=repo,
    )


@router.post("/api/analyze", response_model=JobResponse)
async def create_analysis_job(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(require_auth),
    repo: JobRepository = Depends(get_job_repository),
    runner: AnalysisJobRunner = Depends(get_analysis_runner),
):
    """
    Start an analysis job for one or more areas of interest.

    Returns a Job resource immediately with `status: pending`. The analysis
    runs in the background — poll `GET /api/jobs/{id}` until `status` is
    `completed` or `failed`. When completed, each entry in `resources` contains
    a `resource_url` pointing to the generated insight (e.g.
    `/api/insights/{id}`).

    If `thread_id` is provided the resulting charts and statistics are also
    written into the agent state for that thread, so follow-up chat messages
    can reference the data without re-fetching.
    """
    job_id = await repo.create_job(
        user_id=user.id,
        thread_id=request.thread_id,
        type=JobType.ANALYSIS,
    )

    background_tasks.add_task(
        _run_job,
        job_id=job_id,
        user_id=user.id,
        request=request,
        runner=runner,
    )

    return JobResponse(
        id=job_id,
        type=JobType.ANALYSIS.value,
        status="pending",
        thread_id=request.thread_id,
        resources=[],
        created_at=datetime.now(),
    )


async def _run_job(
    job_id: UUID,
    user_id: str,
    request: AnalyzeRequest,
    runner: AnalysisJobRunner,
):
    await runner.run(
        job_id=job_id,
        user_id=user_id,
        aois=[aoi.model_dump() for aoi in request.aois],
        dataset_id=request.dataset_id,
        start_date=request.start_date,
        end_date=request.end_date,
        thread_id=request.thread_id,
    )
