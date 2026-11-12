"""Zap mode: one prompt to a plan for the map, with no agent."""

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth.dependencies import require_admin
from src.api.schemas import UserModel
from src.api.services.zap.jev import JevError
from src.api.services.zap.models import ZapPlan, ZapRequest
from src.api.services.zap.planner import plan_zap
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/api/zap", response_model=ZapPlan)
async def zap(request: ZapRequest, user: UserModel = Depends(require_admin)):
    """
    Plan the map changes for one prompt with the Clairic extraction model
    (the place, the time, the canopy cover) and the jev decision model (the
    dataset, the area, the forest type). When Clairic fails, jev also gives
    the place, the time and the canopy cover.

    Experimental: admins and superusers only.

    Returns up to three steps (show a dataset, go to an area, chart the
    dataset for the area) for the frontend to run in order, and the jev
    decisions with their probabilities and sources, and the map state after
    the steps (`state`), which the client sends back as `current` with the
    next prompt. Changes nothing on the server: the chart step runs through
    POST /api/analyze.

    On a dashboard page (`current.page` is "dashboard", with
    `current.dashboard_id`), the plan adds content to the dashboard: a
    chart, a map, an analysis template section or Sentinel-2 imagery, for
    the first area of the dashboard. The frontend runs each step through
    the dashboard endpoints (see "Dashboard step contract" in
    docs/zap-mode-plan.md). Only the owner of the dashboard gets steps. A
    plan with a decision that is not clear has `needs_confirmation`.
    """
    try:
        return await plan_zap(request.prompt, request.current, user.id)
    except JevError as exc:
        logger.error("zap_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc))
