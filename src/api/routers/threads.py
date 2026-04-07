"""Thread management and ratings endpoints."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.load import dumps
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.graph import fetch_checkpointer, fetch_zeno
from src.api.auth.dependencies import optional_auth, require_auth
from src.api.data_models import RatingOrm, ThreadOrm, UserType
from src.api.schemas import (
    RatingCreateRequest,
    RatingModel,
    ThreadModel,
    ThreadStateResponse,
    ThreadUpdateRequest,
    UserModel,
)
from src.api.services.chat import langfuse_client, replay_chat
from src.shared.database import get_session_from_pool_dependency
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/api/threads", response_model=list[ThreadModel])
async def list_threads(
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """List all threads belonging to the authenticated user."""
    stmt = select(ThreadOrm).filter_by(user_id=user.id)
    result = await session.execute(stmt)
    threads = result.scalars().all()
    return [ThreadModel.model_validate(thread) for thread in threads]


@router.get("/api/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    user: Optional[UserModel] = Depends(optional_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get thread conversation history - supports both public and private access.

    Public threads (is_public=True) can be accessed by anyone.
    Private threads require authentication and ownership.
    """
    stmt = select(ThreadOrm).filter_by(id=thread_id)
    result = await session.execute(stmt)
    thread = result.scalars().first()

    if not thread:
        logger.warning("Thread not found", thread_id=thread_id)
        raise HTTPException(status_code=404, detail="Thread not found")

    if thread.is_public:
        logger.debug("Accessing public thread", thread_id=thread_id)
    else:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Bearer token",
            )

        if thread.user_id != user.id and user.user_type != UserType.ADMIN:
            logger.warning(
                "Unauthorized access to private thread",
                thread_id=thread_id,
                user_id=user.id,
                owner_id=thread.user_id,
            )
            raise HTTPException(status_code=404, detail="Thread not found")

        if user.user_type == UserType.ADMIN:
            logger.debug(
                "Admin accessing private thread",
                thread_id=thread_id,
                admin_user_id=user.id,
                owner_id=thread.user_id,
            )
        else:
            logger.debug(
                "Accessing private thread",
                thread_id=thread_id,
                user_id=user.id,
            )

    try:
        logger.debug("Replaying thread", thread_id=thread_id)
        return StreamingResponse(
            replay_chat(thread_id=thread_id), media_type="application/x-ndjson"
        )
    except Exception as e:
        logger.exception("Replay failed", thread_id=thread_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/threads/{thread_id}", response_model=ThreadModel)
async def update_thread(
    thread_id: str,
    request: ThreadUpdateRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Update thread properties including name and sharing settings."""
    stmt = select(ThreadOrm).filter_by(user_id=user.id, id=thread_id)
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    for key, value in request.model_dump(exclude_none=True).items():
        if value is not None:
            setattr(thread, key, value)
    await session.commit()
    await session.refresh(thread)
    return ThreadModel.model_validate(thread)


@router.get(
    "/api/threads/{thread_id}/state", response_model=ThreadStateResponse
)
async def get_thread_state(
    thread_id: str,
    user: Optional[UserModel] = Depends(optional_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """
    Get the current agent state for a thread.

    Public threads can be accessed by anyone; private threads require ownership.
    """
    stmt = select(ThreadOrm).filter_by(id=thread_id)
    result = await session.execute(stmt)
    thread = result.scalars().first()

    if not thread:
        logger.warning("Thread not found", thread_id=thread_id)
        raise HTTPException(status_code=404, detail="Thread not found")

    if thread.is_public:
        logger.debug("Accessing public thread state", thread_id=thread_id)
    else:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Bearer token",
            )

        if thread.user_id != user.id:
            logger.warning(
                "Unauthorized access to private thread state",
                thread_id=thread_id,
                user_id=user.id,
                owner_id=thread.user_id,
            )
            raise HTTPException(status_code=404, detail="Thread not found")

        logger.debug(
            "Accessing private thread state",
            thread_id=thread_id,
            user_id=user.id,
        )

    try:
        zeno_async = await fetch_zeno()
        config = {"configurable": {"thread_id": thread_id}}
        state = await zeno_async.aget_state(config=config)

        return ThreadStateResponse(
            thread_id=thread_id,
            state=dumps(state.values),
        )

    except Exception as e:
        logger.exception("Error retrieving thread state", thread_id=thread_id)
        raise HTTPException(
            status_code=500, detail=f"Error retrieving thread state: {str(e)}"
        )


@router.delete("/api/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str,
    user: UserModel = Depends(require_auth),
    checkpointer: AsyncPostgresSaver = Depends(fetch_checkpointer),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Delete thread permanently including its conversation history."""
    await checkpointer.adelete_thread(thread_id)
    stmt = select(ThreadOrm).filter_by(user_id=user.id, id=thread_id)
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    await session.delete(thread)
    await session.commit()
    return {"detail": "Thread deleted successfully"}


async def _send_rating_to_langfuse(
    trace_id: str, rating: int, comment: str, user_id: str
):
    """Send user rating feedback to Langfuse as a score."""
    try:
        langfuse_client.create_score(
            trace_id=trace_id,
            name="user-feedback",
            value=rating,
            comment=comment,
            data_type="NUMERIC",
        )
        logger.info(
            "Rating sent to Langfuse",
            trace_id=trace_id,
            rating=rating,
            user_id=user_id,
        )
    except Exception as e:
        logger.warning(
            "Failed to send rating to Langfuse",
            trace_id=trace_id,
            rating=rating,
            user_id=user_id,
            error=str(e),
        )


@router.post("/api/threads/{thread_id}/rating", response_model=RatingModel)
async def create_or_update_rating(
    thread_id: str,
    request: RatingCreateRequest,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Create or update a rating for a trace in a thread."""
    stmt = select(ThreadOrm).filter_by(id=thread_id, user_id=user.id)
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        raise HTTPException(
            status_code=404, detail="Thread not found or access denied"
        )

    stmt = select(RatingOrm).filter_by(
        user_id=user.id, thread_id=thread_id, trace_id=request.trace_id
    )
    result = await session.execute(stmt)
    existing_rating = result.scalars().first()

    if existing_rating:
        existing_rating.rating = request.rating
        existing_rating.comment = request.comment
        existing_rating.updated_at = datetime.now()
        await session.commit()
        await session.refresh(existing_rating)

        logger.info(
            "Rating updated",
            user_id=user.id,
            thread_id=thread_id,
            trace_id=request.trace_id,
            rating=request.rating,
            comment=request.comment,
        )

        await _send_rating_to_langfuse(
            request.trace_id, request.rating, request.comment, user.id
        )

        return RatingModel.model_validate(existing_rating)
    else:
        new_rating = RatingOrm(
            id=str(uuid.uuid4()),
            user_id=user.id,
            thread_id=thread_id,
            trace_id=request.trace_id,
            rating=request.rating,
            comment=request.comment,
        )
        session.add(new_rating)
        await session.commit()
        await session.refresh(new_rating)

        logger.info(
            "Rating created",
            user_id=user.id,
            thread_id=thread_id,
            trace_id=request.trace_id,
            rating=request.rating,
            comment=request.comment,
        )

        await _send_rating_to_langfuse(
            request.trace_id, request.rating, request.comment, user.id
        )

        return RatingModel.model_validate(new_rating)


@router.get(
    "/api/threads/{thread_id}/rating", response_model=list[RatingModel]
)
async def get_thread_ratings(
    thread_id: str,
    user: UserModel = Depends(require_auth),
    session: AsyncSession = Depends(get_session_from_pool_dependency),
):
    """Get all ratings provided by the authenticated user for a thread."""
    stmt = select(ThreadOrm).filter_by(id=thread_id, user_id=user.id)
    result = await session.execute(stmt)
    thread = result.scalars().first()
    if not thread:
        raise HTTPException(
            status_code=404, detail="Thread not found or access denied"
        )

    stmt = (
        select(RatingOrm)
        .filter_by(user_id=user.id, thread_id=thread_id)
        .order_by(RatingOrm.created_at)
    )
    result = await session.execute(stmt)
    ratings = result.scalars().all()

    logger.info(
        "Thread ratings retrieved",
        user_id=user.id,
        thread_id=thread_id,
        count=len(ratings),
    )

    return [RatingModel.model_validate(rating) for rating in ratings]
