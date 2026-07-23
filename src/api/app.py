import uuid
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.agent.graph import close_checkpointer_pool, get_checkpointer_pool
from src.agent.utils.sgrep import data_status
from src.api.routers import (
    admin,
    analyze,
    aois,
    chat,
    custom_areas,
    dashboards,
    geometry,
    insights,
    jobs,
    metadata,
    mosaic,
    threads,
    thumbnails,
    traces,
    users,
)
from src.shared.config import SharedSettings
from src.shared.database import close_global_pool, initialize_global_pool
from src.shared.logging_config import get_logger
from src.shared.version import get_version

logger = get_logger(__name__)


def _add_cors_headers_for_error(request: Request, response: Response) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    vary = response.headers.get("Vary")
    if vary:
        if "Origin" not in vary:
            response.headers["Vary"] = f"{vary}, Origin"
    else:
        response.headers["Vary"] = "Origin"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Deploy logs must show the *effective* values of host settings that a
    # deployed env var can override: a rotated default in code (e.g. the
    # eoapi cache host) is silently shadowed by a stale override, and tile
    # URLs then break browser-side only, with no server-side signal.
    logger.info(
        "settings_resolved",
        eoapi_base_url=SharedSettings.eoapi_base_url,
        api_base_url=SharedSettings.api_base_url,
    )
    blog_data_ok, blog_data_detail = data_status()
    if blog_data_ok:
        logger.info("Blog search data ready", detail=blog_data_detail)
    else:
        logger.error(
            "Blog search data missing - search_blogs will fail",
            detail=blog_data_detail,
        )
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
        # private: responses require auth, so only browsers should cache.
        response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    """Middleware to log requests and bind request ID to context."""
    req_id = uuid.uuid4().hex
    request.state.request_id = req_id

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
        response = JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal Server Error",
                "request_id": req_id,
            },
        )
        _add_cors_headers_for_error(request, response)
    finally:
        if not response:
            response = Response(
                content="Internal Server Error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        # Error responses produced by exception handlers (e.g. titiler tiler
        # errors -> 404/500) never hit the except branch above, so log them
        # here too — otherwise a failing tile request looks like a normal
        # "Response sent" at INFO.
        log = logger.info
        if response_code is not None and response_code >= 500:
            log = logger.error
        elif response_code is not None and response_code >= 400:
            log = logger.warning
        log(
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
app.include_router(aois.router)
app.include_router(geometry.router)
app.include_router(thumbnails.router)
app.include_router(insights.router)
app.include_router(dashboards.router)
app.include_router(metadata.router)
app.include_router(admin.router)
app.include_router(traces.router)
app.include_router(mosaic.router, prefix="/mosaic", tags=["Map Tiles"])
