"""Chat and quota endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependencies import require_auth
from src.api.config import APISettings
from src.api.data_models import ThreadOrm
from src.api.schemas import ChatRequest, QuotaModel, UserModel
from src.api.services.chat import generate_thread_name, stream_chat
from src.api.services.quota import check_quota, enforce_quota
from src.api.user_profile_configs.sectors import SECTOR_ROLES, SECTORS
from src.shared.database import get_session_from_pool_dependency
from src.shared.logging_config import bind_request_logging_context, get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/api/quota", response_model=QuotaModel)
async def get_quota(
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    quota_info = await check_quota(user, session)
    return quota_info


@router.post("/api/chat")
async def chat(
    request: Request,
    chat_request: ChatRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Chat endpoint for Zeno with quota tracking.

    Accepts a chat query and returns a streamed response. Tracks quota usage
    and includes quota information in response headers when quota checking is enabled.
    """
    bind_request_logging_context(
        thread_id=chat_request.thread_id,
        session_id=chat_request.session_id,
        query=chat_request.query,
    )
    stmt = select(ThreadOrm).filter_by(
        id=chat_request.thread_id, user_id=user.id
    )
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        thread_name = await generate_thread_name(chat_request.query)
        thread = ThreadOrm(
            id=chat_request.thread_id,
            user_id=user.id,
            agent_id="UniGuana",
            name=thread_name,
        )
        session.add(thread)
        await session.commit()
        await session.refresh(thread)
    thread_id = thread.id

    langfuse_metadata = {}

    langfuse_metadata["langfuse_user_id"] = user.id
    langfuse_metadata["langfuse_session_id"] = thread_id

    try:
        quota_info = await enforce_quota(user, session)

        headers = {}
        if APISettings.enable_quota_checking and quota_info:
            headers["X-Prompts-Used"] = str(quota_info["prompts_used"])
            headers["X-Prompts-Quota"] = str(quota_info["prompt_quota"])

        user_dict = {
            "country_code": user.country_code,
            "preferred_language_code": user.preferred_language_code,
            "areas_of_interest": user.areas_of_interest,
        }
        if user.sector_code and user.sector_code in SECTORS:
            user_dict["sector_code"] = SECTORS[user.sector_code]
            if user.role_code and user.role_code in SECTOR_ROLES.get(
                user.sector_code, {}
            ):
                user_dict["role_code"] = SECTOR_ROLES[user.sector_code][
                    user.role_code
                ]

        return StreamingResponse(
            stream_chat(
                query=chat_request.query,
                user_persona=chat_request.user_persona,
                thread_id=thread_id,
                ui_context=chat_request.ui_context,
                ui_action_only=chat_request.ui_action_only,
                langfuse_metadata=langfuse_metadata,
                user=user_dict,
            ),
            media_type="application/x-ndjson",
            headers=headers if headers else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Chat request failed",
            error=str(e),
            error_type=type(e).__name__,
            thread_id=chat_request.thread_id,
        )
        raise HTTPException(status_code=500, detail=str(e))
