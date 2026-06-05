from fastapi import APIRouter, Depends

from src.agent.datasets.handlers.analytics_handler import AnalyticsHandler
from src.api.auth.dependencies import require_auth
from src.api.schemas import AnalyzeRequest, AnalyzeResponse, UserModel
from src.api.services.analyze import AnalyzeService

router = APIRouter()

_handler = AnalyticsHandler()


@router.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    user: UserModel = Depends(require_auth),
):
    service = AnalyzeService(_handler)
    result = await service.analyze(
        aois=[aoi.model_dump() for aoi in request.aois],
        dataset_id=request.dataset_id,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    return AnalyzeResponse(
        success=result.data.success,
        message=result.data.message,
        charts_data=result.charts,
        source_urls=result.source_urls,
    )
