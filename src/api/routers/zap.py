"""Zap mode: one prompt to a plan for the map, with no agent."""

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth.dependencies import require_auth
from src.api.schemas import UserModel
from src.api.services.zap.jev import JevError
from src.api.services.zap.models import ZapPlan, ZapRequest
from src.api.services.zap.planner import plan_zap
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/api/zap", response_model=ZapPlan)
async def zap(request: ZapRequest, user: UserModel = Depends(require_auth)):
    """
    Plan the map changes for one prompt with the jev decision model.

    Returns up to three steps (show a dataset, go to an area, chart the
    dataset for the area) for the frontend to run in order, and the jev
    decisions with their probabilities. Changes nothing on the server: the
    chart step runs through POST /api/analyze.
    """
    try:
        return await plan_zap(request.prompt, request.current, user.id)
    except JevError as exc:
        logger.error("zap_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc))
