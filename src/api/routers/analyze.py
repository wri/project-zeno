"""Analysis endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.agent.datasets.config import DATASETS
from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
from src.api.auth.dependencies import require_auth
from src.api.data_models import InsightOrm
from src.api.routers.insights import row_to_response
from src.api.schemas import AnalyzeRequest, InsightResponse, UserModel
from src.api.services.analysis_runner import (
    AnalysisError,
    AnalysisRunner,
    AnalysisTimeoutError,
)
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import GENERATORS
from src.shared.database import get_session_from_pool

router = APIRouter()

handler = AnalyticsHandler()

CATALOG_DATASET_IDS = {ds["dataset_id"] for ds in DATASETS}


def get_analysis_runner() -> AnalysisRunner:
    return AnalysisRunner(service=AnalyzeService(handler, GENERATORS))


@router.post("/api/analyze", response_model=InsightResponse)
async def analyze(
    request: AnalyzeRequest,
    user: UserModel = Depends(require_auth),
    runner: AnalysisRunner = Depends(get_analysis_runner),
):
    """
    Run an analysis for one or more areas of interest.

    The analysis runs within the request and, on success, returns the
    generated insight — the same shape as `GET /api/insights/{id}` — holding
    deterministic charts and no narrative text. The insight and its charts
    are persisted in a single transaction.

    A failed analysis persists nothing and surfaces as an HTTP error: `502`
    when the analytics pull fails, `504` when it times out. Retrying starts
    clean.
    """
    if request.dataset_id not in CATALOG_DATASET_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown dataset_id: {request.dataset_id}",
        )

    try:
        insight_id = await runner.run(
            user_id=user.id,
            aois=[aoi.model_dump() for aoi in request.aois],
            dataset_id=request.dataset_id,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            thread_id=request.thread_id,
        )
    except AnalysisTimeoutError:
        raise HTTPException(status_code=504, detail="Analysis timed out")
    except AnalysisError:
        raise HTTPException(status_code=502, detail="Analysis failed")

    # The session opens only after the (up to ~50s) analytics pull finished,
    # so no pool connection is held while waiting on the upstream API.
    async with get_session_from_pool() as session:
        result = await session.execute(
            select(InsightOrm)
            .options(selectinload(InsightOrm.charts))
            .where(InsightOrm.id == UUID(insight_id))
        )
        row = result.scalars().one()
        return row_to_response(row)
