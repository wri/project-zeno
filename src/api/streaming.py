"""Streaming utilities for FastAPI endpoints."""

from fastapi import Request

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


async def guarded_stream(request: Request, gen):
    try:
        async for chunk in gen:
            if await request.is_disconnected():
                logger.info("Client disconnected, aborting stream")
                break
            yield chunk
    finally:
        await gen.aclose()
