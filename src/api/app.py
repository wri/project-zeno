import uuid
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.mosaic.errors import MOSAIC_STATUS_CODES

from src.agent.graph import close_checkpointer_pool, get_checkpointer_pool
from src.api.routers import (
    admin,
    analyze,
    chat,
    custom_areas,
    geometry,
    imager,
    insights,
    jobs,
    metadata,
    threads,
    thumbnails,
    traces,
    users,
)
from src.shared.database import close_global_pool, initialize_global_pool
from src.shared.logging_config import get_logger
from src.shared.version import get_version

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
    version=get_version(),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Next-Cursor"],
)


@app.middleware("http")
async def mosaic_cache_headers(request: Request, call_next) -> Response:
    """Mosaic tiles are immutable per token; let browsers cache them."""
    response = await call_next(request)
    if (
        request.method == "GET"
        and request.url.path.startswith("/mosaic/")
        and response.status_code == 200
    ):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


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
    response: Optional[Response] = None

    try:
        response = await call_next(request)
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


app.include_router(analyze.router)
app.include_router(jobs.router)
app.include_router(chat.router)
app.include_router(threads.router)
app.include_router(users.router)
app.include_router(custom_areas.router)
app.include_router(geometry.router)
app.include_router(thumbnails.router)
app.include_router(insights.router)
app.include_router(metadata.router)
app.include_router(admin.router)
app.include_router(traces.router)
app.include_router(imager.router, prefix="/mosaic", tags=["Map Tiles"])

# Map titiler/cogeo-mosaic errors to proper status codes (e.g. tile requests
# outside the mosaic bounds -> 404, unknown mosaic id -> 404). The catch-all
# Exception entry is dropped to leave non-tiler error handling unchanged.
_tiler_status_codes = {**DEFAULT_STATUS_CODES, **MOSAIC_STATUS_CODES}
_tiler_status_codes.pop(Exception, None)
add_exception_handlers(app, _tiler_status_codes)
