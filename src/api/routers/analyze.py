"""Analysis job endpoint."""

from fastapi import APIRouter, Depends, HTTPException

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
from src.api.auth.dependencies import require_auth
from src.api.repositories.job_repository import get_job_repository
from src.api.routers.jobs import job_to_response
from src.api.schemas import AnalyzeRequest, JobResponse, UserModel
from src.api.services.analysis_job import AnalysisJobRunner
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import GENERATORS
from src.api.services.job import JobRepository

router = APIRouter()

handler = AnalyticsHandler()

CATALOG_DATASET_IDS = {ds["dataset_id"] for ds in DATASETS}


def get_analysis_runner(
    repo: JobRepository = Depends(get_job_repository),
) -> AnalysisJobRunner:
    return AnalysisJobRunner(
        service=AnalyzeService(handler, GENERATORS),
        repo=repo,
    )


@router.post("/api/analyze", response_model=JobResponse)
async def create_analysis_job(
    request: AnalyzeRequest,
    user: UserModel = Depends(require_auth),
    runner: AnalysisJobRunner = Depends(get_analysis_runner),
):
    """
    Run an analysis for one or more areas of interest.

    The analysis runs within the request: the response is a Job resource that
    is already terminal — `status` is `completed` or `failed`. When completed,
    each entry in `resources` contains a `resource_url` pointing to the
    generated insight (e.g. `/api/insights/{id}`). The job can be re-fetched
    later via `GET /api/jobs/{id}`.

    The job, its insight and charts are persisted in a single transaction once
    the analysis finishes — a failure at any point leaves no partial state.
    """
    if request.dataset_id not in CATALOG_DATASET_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown dataset_id: {request.dataset_id}",
        )

    job = await runner.run(
        user_id=user.id,
        aois=[aoi.model_dump() for aoi in request.aois],
        dataset_id=request.dataset_id,
        start_date=request.start_date.isoformat(),
        end_date=request.end_date.isoformat(),
        thread_id=request.thread_id,
    )
    return job_to_response(job)
