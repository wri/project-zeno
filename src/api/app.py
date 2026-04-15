import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from src.agent.graph import close_checkpointer_pool, get_checkpointer_pool
from src.api.routers import (
    chat,
    custom_areas,
    geometry,
    insights,
    metadata,
    threads,
    users,
)
from src.shared.database import close_global_pool, initialize_global_pool
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_global_pool()
    await get_checkpointer_pool()
    yield
    await close_global_pool()
    await close_checkpointer_pool()


app = FastAPI(
    lifespan=lifespan,
    title="Zeno API",
    description="API for Zeno LangGraph-based agent workflow",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    """Middleware to log requests and bind request ID to context."""
    req_id = uuid.uuid4().hex

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=req_id)

    logger.info(
        "Request started",
        method=request.method,
        url=str(request.url),
        request_id=req_id,
    )
    response_code = None
    response = None

    try:
        response: Response = await call_next(request)
        response_code = response.status_code
    except Exception as e:
        logger.exception(
            "Request failed with error",
            method=request.method,
            url=str(request.url),
            error=str(e),
            request_id=req_id,
        )
        response_code = 500
        raise e
    finally:
        if not response:
            response = Response(
                content="Internal Server Error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        logger.info(
            "Response sent",
            method=request.method,
            url=str(request.url),
            status_code=response_code,
            request_id=req_id,
        )
    return response


app.include_router(chat.router)
app.include_router(threads.router)
app.include_router(users.router)
app.include_router(custom_areas.router)
app.include_router(geometry.router)
app.include_router(insights.router)
app.include_router(metadata.router)
