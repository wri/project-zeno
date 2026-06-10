"""Generic job status endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from src.api.auth.dependencies import require_auth
from src.api.repositories.job_repository import DBJobRepository
from src.api.schemas import JobResourceResponse, JobResponse, UserModel
from src.api.services.job import JobStatus

router = APIRouter()


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
        description="ID of the job returned by the endpoint that created it."
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
