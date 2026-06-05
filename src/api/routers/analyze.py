from fastapi import APIRouter, Depends

from src.agent.datasets.handlers.analytics_handler import (
    TREE_COVER_LOSS_ID,
    AnalyticsHandler,
)
from src.agent.graph import fetch_zeno
from src.api.auth.dependencies import require_auth
from src.api.schemas import AnalyzeRequest, AnalyzeResponse, UserModel
from src.api.services.analyze import AnalyzeService
from src.api.services.charts import TCLChartGenerator

router = APIRouter()

handler = AnalyticsHandler()
generators = [TCLChartGenerator(TREE_COVER_LOSS_ID)]


@router.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    user: UserModel = Depends(require_auth),
):
    service = AnalyzeService(handler, generators)
    result = await service.analyze(
        aois=[aoi.model_dump() for aoi in request.aois],
        dataset_id=request.dataset_id,
        start_date=request.start_date,
        end_date=request.end_date,
    )

    if result.data.success and request.thread_id:
        zeno = await fetch_zeno()
        config = {"configurable": {"thread_id": request.thread_id}}
        await zeno.aupdate_state(
            config,
            {
                "charts_data": result.charts or [],
                "aoi_selection": {
                    "aois": [aoi.model_dump() for aoi in request.aois],
                    "name": request.aois[0].name,
                },
                "dataset": {"dataset_id": request.dataset_id},
                "start_date": request.start_date,
                "end_date": request.end_date,
            },
        )

    return AnalyzeResponse(
        success=result.data.success,
        message=result.data.message,
        charts_data=result.charts,
        source_urls=result.source_urls,
    )
