import json
import os
from typing import Dict, Optional
from uuid import UUID
import uuid
import cachetools
import requests
from datetime import date

import structlog

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from itsdangerous import BadSignature, TimestampSigner
from langchain_core.load import dumps
from langchain_core.messages import HumanMessage
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel, Field
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert

from src.agents.agents import zeno, zeno_anonymous, checkpointer
from src.api.data_models import (
    ThreadModel,
    ThreadOrm,
    UserType,
    UserModel,
    UserOrm,
    DailyUsageOrm,
    CustomAreaOrm,
    CustomAreaModel,
    CustomAreaCreate,
    GeometryResponse,
)
from src.utils.logging_config import bind_request_logging_context, get_logger
from src.utils.env_loader import load_environment_variables
from src.utils.config import APISettings
from src.utils.geocoding_helpers import SOURCE_ID_MAPPING

# Load environment variables using shared utility
load_environment_variables()

logger = get_logger(__name__)


# TODO: how to diferentiate between admin and regular users for limits?
# For now, we assume all users are regular users
# Question: will there be only 2 usage tiers? Do we want to set a default
# daily limit and then set custom limits for specific users? (we can use this
# approach to set daily quotas to -1 for unlimited users)
# DAILY_QUOTA_WARNING_THRESHOLD = 5
# ADMIN_USER_DAILY_QUOTA = 100
# REGULAR_USER_DAILY_QUOTA = 25
# ANONYMOUS_USER_DAILY_QUOTA = 10
# ENABLE_QUOTA_CHECKING = True


app = FastAPI(
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
    structlog.contextvars.bind_contextvars(
        request_id=req_id,
    )

    # Log request start
    logger.info(
        "Request started",
        method=request.method,
        url=str(request.url),
        request_id=req_id,
    )
    response_code = None

    # Call the next middleware or endpoint
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
        # Log request end
        logger.info(
            "Response sent",
            method=request.method,
            url=str(request.url),
            status_code=response_code,
            request_id=req_id,
        )
    return response


langfuse_handler = CallbackHandler()

# HTTP Middleware to asign/verify anonymous session IDs
signer = TimestampSigner(os.environ["COOKIE_SIGNER_SECRET_KEY"])


@app.middleware("http")
async def anonymous_id_middleware(request: Request, call_next):
    anon_cookie = request.cookies.get("anonymous_id")
    need_new = True

    if anon_cookie:
        try:
            # Verify signature & extract payload
            _ = signer.unsign(anon_cookie, max_age=365 * 24 * 3600)  # Cookie age: 1yr
            need_new = False
        except BadSignature:
            pass

    if need_new:
        raw_uuid = str(uuid.uuid4())
        signed = signer.sign(raw_uuid).decode()
    else:
        signed = anon_cookie

    request.state.anonymous_id = signed

    response: Response = await call_next(request)

    response.set_cookie(
        "anonymous_id",
        signed,
        max_age=365 * 24 * 3600,  # Cookie age: 1yr
        # secure=True,  # only over HTTPS
        httponly=True,  # JS cannot read
        samesite="Lax",
    )

    return response


class ChatRequest(BaseModel):
    query: str = Field(..., description="The query")
    user_persona: Optional[str] = Field(None, description="The user persona")

    # UI Context - can include multiple selections
    ui_context: Optional[dict] = (
        None  # {"aoi_selected": {...}, "dataset_selected": {...}, "daterange_selected": {...}}
    )

    # Pure UI actions - no query
    ui_action_only: Optional[bool] = False

    # Chat info
    thread_id: Optional[str] = Field(None, description="The thread ID")
    metadata: Optional[dict] = Field(None, description="The metadata")
    session_id: Optional[str] = Field(None, description="The session ID")
    user_id: Optional[str] = Field(None, description="The user ID")
    tags: Optional[list] = Field(None, description="The tags")


def pack(data):
    return json.dumps(data) + "\n"


def replay_chat(thread_id):
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    try:
        # Fetch checkpoints for conversation/thread
        checkpoints = zeno.get_state_history(config=config)
        # consume checkpoints and sort them by step to process from
        # oldest to newest
        checkpoints = sorted(list(checkpoints), key=lambda x: x.metadata["step"])
        # Remove step -1 which is the initial empty state
        checkpoints = [c for c in checkpoints if c.metadata["step"] >= 0]

        # Variables to track rendered state elements and messages
        # so that we essentially just render the diff of the state
        # from one checkpoint to the next (in order to maintain the
        # correct ordering of messages and state updates)
        rendered_state_elements = {"messages": []}

        for checkpoint in checkpoints:

            update = {"messages": []}

            for message in checkpoint.values.get("messages", []):
                # Assert that message has content, and hasn't already been rendered
                if (
                    message.id in rendered_state_elements["messages"]
                    or not message.content
                ):
                    continue
                rendered_state_elements["messages"].append(message.id)

                update["messages"].append(message)

            # Render the rest of the state updates
            for key, value in checkpoint.values.items():

                if key == "messages":
                    continue  # Skip messages, already handled above

                # Skip if this state element has already been rendered
                if value in rendered_state_elements.setdefault(key, []):
                    continue
                rendered_state_elements[key].append(value)

                update[key] = value

            yield pack({"node": "agent", "update": dumps(update)})

    except Exception as e:
        logger.exception("Error during chat replay: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def stream_chat(
    query: str,
    user_persona: Optional[str] = None,
    ui_context: Optional[dict] = None,
    ui_action_only: Optional[bool] = False,
    thread_id: Optional[str] = None,
    metadata: Optional[Dict] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[list] = None,
):
    # Populate langfuse metadata
    if metadata:
        langfuse_handler.metadata = metadata
    if session_id:
        langfuse_handler.session_id = session_id
    if user_id:
        langfuse_handler.user_id = user_id
    if tags:
        langfuse_handler.tags = tags

    config = {
        # "callbacks": [langfuse_handler],
    }

    messages = []
    ui_action_message = []
    state_updates = {}

    if ui_context:
        for action_type, action_data in ui_context.items():
            match action_type:
                case "aoi_selected":
                    content = f"User selected AOI in UI: {action_data['aoi_name']}"
                    state_updates["aoi"] = action_data["aoi"]
                    state_updates["aoi_name"] = action_data["aoi_name"]
                    state_updates["subregion_aois"] = action_data["subregion_aois"]
                    state_updates["subregion"] = action_data["subregion"]
                    state_updates["subtype"] = action_data["subtype"]
                case "dataset_selected":
                    content = f"User selected dataset in UI: {action_data['dataset']['data_layer']}"
                    state_updates["dataset"] = action_data["dataset"]
                case "daterange_selected":
                    content = f"User selected daterange in UI: start_date:  {action_data['start_date']}, end_date: {action_data['end_date']}"
                    state_updates["start_date"] = action_data["start_date"]
                    state_updates["end_date"] = action_data["end_date"]
                case _:
                    content = f"User performed action in UI: {action_type}"
            ui_action_message.append(content)

    ui_message = HumanMessage(content="\n".join(ui_action_message))
    messages.append(ui_message)

    if not ui_action_only and query:
        messages.append(HumanMessage(content=query))
    else:
        # UI action only, no query, agent should acknowledge the UI updates & ask what's next
        messages.append(
            HumanMessage(
                content="User performed UI action only. Acknowledge the updates and ask what they would like to do next with their selections."
            )
        )

    state_updates["messages"] = messages
    state_updates["user_persona"] = user_persona
    try:
        # Use zeno_anonymous (zeno agent without checkpointer) for
        # anonymous users by default
        zeno_agent = zeno_anonymous
        if thread_id:
            # thread_id is provided if the user is authenticated,
            # use main zeno agent (with checkpointer)
            zeno_agent = zeno
            config["configurable"] = {"thread_id": thread_id}

        stream = zeno_agent.stream(
            state_updates,
            config=config,
            stream_mode="updates",
            subgraphs=False,
        )

        for update in stream:
            try:
                node = next(iter(update.keys()))
                yield pack(
                    {
                        "node": node,
                        "update": dumps(update[node]),
                    }
                )
            except Exception as e:
                # Send error as a stream event instead of raising
                yield pack(
                    {
                        "node": "error",
                        "update": dumps(
                            {
                                "error": True,
                                "message": str(e),  # String representation of the error
                                "error_type": type(e).__name__,  # Exception class name
                                "type": "stream_processing_error",
                            }
                        ),
                    }
                )
                # Continue processing other updates if possible
                continue

    except Exception as e:
        logger.exception("Error during chat streaming: %s", e)
        # Initial stream setup error - send as error event
        yield pack(
            {
                "node": "error",
                "update": dumps(
                    {
                        "error": True,
                        "message": str(e),  # String representation of the error
                        "error_type": type(e).__name__,  # Exception class name
                        "type": "stream_initialization_error",
                        "fatal": True,  # Indicates stream cannot continue
                    }
                ),
            }
        )


# TODO: use connection pooling
def get_session():
    engine = create_engine(APISettings.database_url)

    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with Session() as session:
        yield session


# LRU cache for user info, keyed by token
_user_info_cache = cachetools.TTLCache(maxsize=1024, ttl=60 * 60 * 24)  # 1 day


@cachetools.cached(_user_info_cache)
def fetch_user_from_rw_api(
    authorization: Optional[str] = Header(None),
    domains_allowlist: Optional[str] = ",".join(APISettings.domains_allowlist),
) -> UserModel:

    if not authorization:
        return None

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
        )

    token = authorization.split(" ")[1]
    try:
        resp = requests.get(
            "https://api.resourcewatch.org/auth/user/me",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=10,
        )
    except Exception as e:
        logger.exception(f"Error contacting Resource Watch: {e}")
        raise HTTPException(
            status_code=502, detail=f"Error contacting Resource Watch: {e}"
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    user_info = resp.json()
    if "name" not in user_info:
        logger.warning(
            "User info does not contain 'name' field, using email account name as fallback",
            email=user_info.get("email", None),
        )
        user_info["name"] = user_info["email"].split("@")[0]

    if isinstance(domains_allowlist, str):
        domains_allowlist = domains_allowlist.split(",")

    if user_info["email"].split("@")[-1].lower() not in domains_allowlist:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not allowed to access this API",
        )

    return UserModel.model_validate(user_info)


async def require_auth(
    user_info: UserModel = Depends(fetch_user_from_rw_api), session=Depends(get_session)
) -> UserModel:
    """
    Requires Authorization - raises HTTPException if not authenticated
    """
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Authorization header is required",
        )

    user = session.query(UserOrm).filter_by(id=user_info.id).first()
    if not user:
        user = UserOrm(**user_info.model_dump())
        session.add(user)
        session.commit()
        session.refresh(user)
    # Convert to Pydantic model while session is open
    user_model = UserModel.model_validate(user)
    # Bind user info to request context for logging
    bind_request_logging_context(user_id=user_model.id)
    return user_model


async def optional_auth(
    user_info: UserModel = Depends(fetch_user_from_rw_api), session=Depends(get_session)
) -> Optional[UserModel]:
    """
    Optional Authorization - returns None if not authenticated, UserModel if authenticated
    """
    if not user_info:
        return None

    user = session.query(UserOrm).filter_by(id=user_info.id).first()
    if not user:
        user = UserOrm(**user_info.model_dump())
        session.add(user)
        session.commit()
        session.refresh(user)
    # Convert to Pydantic model while session is open
    user_model = UserModel.model_validate(user)
    # Bind user info to request context for logging
    bind_request_logging_context(user_id=user_model.id)
    return user_model


# Keep the old function for backward compatibility during transition
async def fetch_user(
    user_info: UserModel = Depends(fetch_user_from_rw_api), session=Depends(get_session)
):
    """
    Deprecated: Use require_auth() or optional_auth() instead
    """
    return await optional_auth(user_info, session)


def check_quota(
    request: Request,
    user: Optional[UserModel] = Depends(fetch_user_from_rw_api),
    session=Depends(get_session),
):

    if not APISettings.enable_quota_checking:
        return {}

    # 1. Get calling user and set quota
    if not user:
        daily_quota = APISettings.anonymous_user_daily_quota
        if anon := request.cookies.get("anon_id"):
            identity = f"anon:{anon}"
        else:
            identity = f"anon:{request.state.anonymous_id}"

    else:
        daily_quota = (
            APISettings.admin_user_daily_quota
            if user.user_type == UserType.ADMIN
            else APISettings.regular_user_daily_quota
        )
        identity = f"user:{user.id}"

    today = date.today()

    # 2. Atomically "insert or increment" with ON CONFLICT
    stmt = (
        insert(DailyUsageOrm)
        .values(id=identity, date=today, usage_count=1)
        # Composite PK = (id, date)
        .on_conflict_do_update(
            index_elements=["id", "date"],
            set_={"usage_count": DailyUsageOrm.usage_count + 1},
        )
        .returning(DailyUsageOrm.usage_count)
    )
    result = session.execute(stmt)
    count = result.scalar()
    session.commit()  # commit the upsert

    # 3. Enforce the quota
    if count > daily_quota:
        raise HTTPException(
            status_code=429,
            detail=f"Daily free limit of {daily_quota} exceeded; please try again tomorrow.",
        )

    if count >= daily_quota - APISettings.daily_quoata_warning_threshold:
        return {
            "warning": f"User {identity} is approaching daily quota limit ({count} prompts out of {daily_quota})"
        }

    return {}


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    user: Optional[UserModel] = Depends(optional_auth),
    quota_info: dict = Depends(check_quota),
    session=Depends(get_session),
):
    """
    Chat endpoint for Zeno.

    Args:
        request: The chat request
        user: The user, authenticated against the WRI API (injected via FastAPI dependency)

    Returns:
        The streamed response
    """

    thread_id = None
    thread = None

    if user:
        # For authenticated users, persist threads in database
        bind_request_logging_context(
            thread_id=request.thread_id,
            session_id=request.session_id,
            query=request.query,
        )
        thread = (
            session.query(ThreadOrm)
            .filter_by(id=request.thread_id, user_id=user.id)
            .first()
        )
        if not thread:
            thread = ThreadOrm(
                id=request.thread_id, user_id=user.id, agent_id="UniGuana"
            )
            session.add(thread)
            session.commit()
            session.refresh(thread)
        thread_id = thread.id
    else:
        # For anonymous users, use the thread_id from request but don't persist
        # This allows conversation continuity within the same session
        thread_id = request.thread_id

    try:
        headers = {}
        if "warning" in quota_info:
            headers["X-Quota-Warning"] = quota_info["warning"]

        return StreamingResponse(
            stream_chat(
                query=request.query,
                user_persona=request.user_persona,
                thread_id=thread_id,
                ui_context=request.ui_context,
                ui_action_only=request.ui_action_only,
                metadata=request.metadata,
                session_id=request.session_id,
                user_id=request.user_id,
                tags=request.tags,
            ),
            media_type="application/x-ndjson",
            headers=headers if headers else None,
        )
    except Exception as e:
        logger.exception(
            "Chat request failed",
            error=str(e),
            error_type=type(e).__name__,
            thread_id=request.thread_id,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/threads", response_model=list[ThreadModel])
def list_threads(user: UserModel = Depends(require_auth), session=Depends(get_session)):
    """
    Requires Authorization
    """
    threads = session.query(ThreadOrm).filter_by(user_id=user.id).all()
    return [ThreadModel.model_validate(thread) for thread in threads]


@app.get("/api/threads/{thread_id}")
def get_thread(
    thread_id: str,
    user: UserModel = Depends(require_auth),
    session=Depends(get_session),
):
    """
    Requires Authorization
    """
    thread = session.query(ThreadOrm).filter_by(user_id=user.id, id=thread_id).first()
    if not thread:
        logger.warning("Thread not found", thread_id=thread_id)
        raise HTTPException(status_code=404, detail="Thread not found")

    thread_id = thread.id

    try:
        logger.debug("Replaying thread", thread_id=thread_id)
        return StreamingResponse(
            replay_chat(thread_id=thread_id),
            media_type="application/x-ndjson",
        )
    except Exception as e:
        logger.exception("Replay failed", thread_id=thread_id)
        raise HTTPException(status_code=500, detail=str(e))


class ThreadUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="The name of the thread")


@app.patch("/api/threads/{thread_id}", response_model=ThreadModel)
def update_thread(
    thread_id: str,
    request: ThreadUpdateRequest,
    user: UserModel = Depends(require_auth),
    session=Depends(get_session),
):
    """
    Requires Authorization
    """
    thread = session.query(ThreadOrm).filter_by(user_id=user.id, id=thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    for key, value in request.model_dump().items():
        setattr(thread, key, value)
    session.commit()
    session.refresh(thread)
    return ThreadModel.model_validate(thread)


@app.delete("/api/threads/{thread_id}", status_code=204)
def delete_thread(
    thread_id: str,
    user: UserModel = Depends(require_auth),
    session=Depends(get_session),
):
    """
    Requires Authorization
    """

    checkpointer.delete_thread(thread_id)

    thread = session.query(ThreadOrm).filter_by(user_id=user.id, id=thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    session.delete(thread)
    session.commit()
    return {"detail": "Thread deleted successfully"}


@app.get("/api/geometry/{source}/{src_id}", response_model=GeometryResponse)
async def get_geometry(source: str, src_id: str):
    """
    Get geometry data by source and source ID.

    Args:
        source: Source type (gadm, kba, landmark, wdpa)
        src_id: Source-specific ID (GID_X for GADM, sitrecid for KBA, etc.)
        user: Authenticated user

    Returns:
        Geometry data with name, subtype, and GeoJSON geometry

    Example:
        GET /api/geometry/gadm/IND.26.2_1
        GET /api/geometry/kba/16595
    """
    if source not in SOURCE_ID_MAPPING:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source: {source}. Must be one of: {', '.join(SOURCE_ID_MAPPING.keys())}",
        )

    table_name = SOURCE_ID_MAPPING[source]["table"]
    id_column = SOURCE_ID_MAPPING[source]["id_column"]

    sql_query = f"""
        SELECT name, subtype, ST_AsGeoJSON(geometry) as geometry_json
        FROM {table_name}
        WHERE "{id_column}" = :src_id
    """

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql_query), {"src_id": src_id}).fetchone()

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Geometry not found for source '{source}' with ID {src_id}",
            )

        # Parse GeoJSON string
        try:
            geometry = (
                json.loads(result.geometry_json) if result.geometry_json else None
            )
        except json.JSONDecodeError:
            logger.error(f"Failed to parse GeoJSON for {source}:{src_id}")
            geometry = None

        return GeometryResponse(
            name=result.name,
            subtype=result.subtype,
            source=source,
            src_id=src_id,
            geometry=geometry,
        )

    except Exception as e:
        logger.exception(f"Error fetching geometry for {source}:{src_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/me", response_model=UserModel)
async def auth_me(user: UserModel = Depends(require_auth)):
    """
    Requires Authorization: Bearer <JWT>
    Forwards the JWT to Resource Watch API and returns user info.
    """

    return user


@app.get("/api/metadata")
async def api_metadata() -> dict:
    """
    Returns API metadata that's helpful for instantiating the frontend.

    Note:
    For `layer_id_mapping`, the keys are the source names (e.g., `gadm`, `kba`, etc.)
    and the values are the corresponding ID columns used in the database.

    The frontend can get these IDs from the vector tile layer and use the `/api/geometry/{source}/{src_id}`
    endpoint to fetch the geometry data.

    The GADM layer needs some special handling:

    The gadm layer uses a composite ID format like `IND.26.2_1` that's derived from
    the GADM hierarchy, so the ID column is just `gadm_id` in the database but on the frontend
    it will be displayed as `GID_X` where X is the GADM level (1-5).

    The frontend will have to check the level of the selected GADM geometry and use the corresponding
    `GID_X` field to get the correct ID for the API call.

    For example, if the user selects a GADM level 2 geometry,
    the ID will look something like `IND.26.2_1` and should be available in the gid_2 field on the
    vector tile layer.
    """
    return {
        "version": "0.1.0",
        "layer_id_mapping": {
            key: value["id_column"] for key, value in SOURCE_ID_MAPPING.items()
        },
    }


@app.post("/api/custom_areas/", response_model=CustomAreaModel)
def create_custom_area(
    area: CustomAreaCreate,
    user: UserModel = Depends(require_auth),
    session=Depends(get_session),
):
    """Create a new custom area for the authenticated user."""
    custom_area = CustomAreaOrm(
        user_id=user.id,
        name=area.name,
        geometries=[i.model_dump_json() for i in area.geometries],
    )
    session.add(custom_area)
    session.commit()
    session.refresh(custom_area)

    return CustomAreaModel(
        id=custom_area.id,
        user_id=custom_area.user_id,
        name=custom_area.name,
        created_at=custom_area.created_at,
        updated_at=custom_area.updated_at,
        geometries=[json.loads(i) for i in custom_area.geometries],
    )


@app.get("/api/custom_areas/", response_model=list[CustomAreaModel])
def list_custom_areas(
    user: UserModel = Depends(require_auth), session=Depends(get_session)
):
    """List all custom areas belonging to the authenticated user."""
    areas = session.query(CustomAreaOrm).filter_by(user_id=user.id).all()
    results = []
    for area in areas:
        area.geometries = [json.loads(i) for i in area.geometries]
        results.append(area)
    return results


@app.get("/api/custom_areas/{area_id}", response_model=CustomAreaModel)
def get_custom_area(
    area_id: UUID,
    user: UserModel = Depends(require_auth),
    session=Depends(get_session),
):
    """Get a specific custom area by ID."""
    custom_area = (
        session.query(CustomAreaOrm).filter_by(id=area_id, user_id=user.id).first()
    )
    if not custom_area:
        raise HTTPException(status_code=404, detail="Custom area not found")

    return CustomAreaModel(
        id=custom_area.id,
        user_id=custom_area.user_id,
        name=custom_area.name,
        created_at=custom_area.created_at,
        updated_at=custom_area.updated_at,
        geometries=[json.loads(i) for i in custom_area.geometries],
    )


@app.patch("/api/custom_areas/{area_id}", response_model=CustomAreaModel)
def update_custom_area_name(
    area_id: UUID,
    payload: dict,
    user: UserModel = Depends(require_auth),
    session=Depends(get_session),
):
    """Update the name of a custom area."""
    area = session.query(CustomAreaOrm).filter_by(id=area_id, user_id=user.id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Custom area not found")
    area.name = payload["name"]
    session.commit()
    session.refresh(area)

    return CustomAreaModel(
        id=area.id,
        user_id=area.user_id,
        name=area.name,
        created_at=area.created_at,
        updated_at=area.updated_at,
        geometries=[json.loads(i) for i in area.geometries],
    )


@app.delete("/api/custom_areas/{area_id}", status_code=204)
def delete_custom_area(
    area_id: UUID,
    user: UserModel = Depends(require_auth),
    session=Depends(get_session),
):
    """Delete a custom area."""
    area = session.query(CustomAreaOrm).filter_by(id=area_id, user_id=user.id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Custom area not found")
    session.delete(area)
    session.commit()
