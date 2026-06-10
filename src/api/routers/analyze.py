from datetime import datetime
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Response,
)

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
)
from src.api.auth.dependencies import require_auth
from src.api.repositories.job_repository import DBJobRepository
from src.api.schemas import (
    AnalyzeRequest,
    JobResourceResponse,
    JobResponse,
    UserModel,
)
from src.api.services.analysis_job import AnalysisJobRunner
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import TCLChartGenerator
from src.api.services.job import JobStatus, JobType

router = APIRouter()

handler = AnalyticsHandler()
generators = [TCLChartGenerator(TREE_COVER_LOSS_ID)]


def _make_runner() -> AnalysisJobRunner:
    return AnalysisJobRunner(
        service=AnalyzeService(handler, generators),
        repo=DBJobRepository(),
    )


@router.post("/api/analyze", response_model=JobResponse)
async def create_analysis_job(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    user: UserModel = Depends(require_auth),
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
    repo = DBJobRepository()
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
    )

    return JobResponse(
        id=job_id,
        type=JobType.ANALYSIS.value,
        status="pending",
        thread_id=request.thread_id,
        resources=[],
        created_at=datetime.now(),
    )


@router.get(
    "/api/jobs/{job_id}",
    response_model=JobResponse,
    responses={
        200: {
            "headers": {
                "Retry-After": {
                    "description": (
                        "Seconds to wait before polling again. "
                        "Present only when status is `pending` or `running`."
                    ),
                    "schema": {"type": "integer", "example": 1},
                }
            }
        }
    },
)
async def get_job(
    response: Response,
    job_id: UUID = Path(
        description="ID of the job returned by POST /api/analyze."
    ),
    user: UserModel = Depends(require_auth),
):
    """
    Get the current status of a job.

    While the job is `pending` or `running` the response includes a
    `Retry-After: 1` header — poll again after that many seconds. Once
    `status` is `completed`, `resources` contains one or more entries each
    with a `resource_url` you can follow to retrieve the result (e.g.
    `GET /api/insights/{id}`). If the job `failed`, `resources` will be
    empty.
    """
    repo = DBJobRepository()
    job = await repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
        response.headers["Retry-After"] = "1"
    return JobResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        thread_id=job.thread_id,
        created_at=job.created_at,
        resources=[
            JobResourceResponse(
                id=r.id,
                resource_url=r.resource_url,
                status=r.status.value,
                created_at=r.created_at,
            )
            for r in job.resources
        ],
    )


async def _run_job(job_id: UUID, user_id: str, request: AnalyzeRequest):
    await _make_runner().run(
        job_id=job_id,
        user_id=user_id,
        aois=[aoi.model_dump() for aoi in request.aois],
        dataset_id=request.dataset_id,
        start_date=request.start_date,
        end_date=request.end_date,
        thread_id=request.thread_id,
    )
