import json
import os
from typing import Dict, Optional
from uuid import UUID
import uuid

import cachetools
import requests
# Load environment variables using shared utility
from src.utils.env_loader import load_environment_variables

load_environment_variables()

from fastapi import (
    Depends, FastAPI, Header, HTTPException, Request, Response, status
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.load import dumps
from langchain_core.messages import HumanMessage
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel, Field
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import structlog

from src.agents.agents import zeno
from src.api.data_models import (ThreadModel, ThreadOrm, UserModel, UserOrm,
                               CustomAreaModel, CustomAreaOrm, CustomAreaCreate)
from src.utils.env_loader import load_environment_variables
from src.utils.logging_config import bind_request_logging_context, get_logger

load_environment_variables()


logger = get_logger(__name__)

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

    # Call the next middleware or endpoint
    try:
        response: Response = await call_next(request)
    except Exception as e:
        logger.exception(
            "Request failed with error",
            method=request.method,
            url=str(request.url),
            error=str(e),
            request_id=req_id,
        )
        raise e
    finally:
        # Log request end
        logger.info(
            "Response sent",
            method=request.method,
            url=str(request.url),
            status_code=response.status_code,
            request_id=req_id,
        )
    return response


langfuse_handler = CallbackHandler()


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

                # TODO: add checkpoint timestamp to message?
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

            mtypes = set(m.type for m in update["messages"])

            node_type = (
                "agent"
                if mtypes == {"ai"} or len(mtypes) > 1
                else "tools" if mtypes == {"tool"} else "human"
            )

            yield pack({"node": node_type, "update": dumps(update)})

    except Exception as e:
        # TODO: yield a stream event with the error?
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
        "configurable": {
            "thread_id": thread_id,
        },
        "callbacks": [langfuse_handler],
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
        stream = zeno.stream(
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


DOMAINS_ALLOWLIST = os.environ.get("DOMAINS_ALLOWLIST", "")
DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)


def get_session():
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with Session() as session:
        yield session


# LRU cache for user info, keyed by token
_user_info_cache = cachetools.TTLCache(maxsize=1024, ttl=60 * 60 * 24)  # 1 day


@cachetools.cached(_user_info_cache)
def fetch_user_from_rw_api(
    authorization: str = Header(...),
    domains_allowlist: Optional[str] = DOMAINS_ALLOWLIST,
) -> UserModel:
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


async def fetch_user(
    user_info: UserModel = Depends(fetch_user_from_rw_api), session=Depends(get_session)
):
    """
    Requires Authorization
    """

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


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    user: UserModel = Depends(fetch_user),
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
    bind_request_logging_context(
        thread_id=request.thread_id, session_id=request.session_id, query=request.query
    )
    thread = (
        session.query(ThreadOrm).filter_by(id=request.thread_id, user_id=user.id).first()
    )
    if not thread:
        thread = ThreadOrm(
            id=request.thread_id, user_id=user.id, agent_id="UniGuana"
        )
        session.add(thread)
        session.commit()
        session.refresh(thread)

    try:
        return StreamingResponse(
            stream_chat(
                query=request.query,
                user_persona=request.user_persona,
                ui_context=request.ui_context,
                ui_action_only=request.ui_action_only,
                thread_id=request.thread_id,
                metadata=request.metadata,
                session_id=request.session_id,
                user_id=request.user_id,
                tags=request.tags,
            ),
            media_type="application/x-ndjson",
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
def list_threads(
    user: UserModel = Depends(fetch_user), session=Depends(get_session)
):
    """
    Requires Authorization
    """
    threads = session.query(ThreadOrm).filter_by(user_id=user.id).all()
    return [ThreadModel.model_validate(thread) for thread in threads]


@app.get("/api/threads/{thread_id}")
def get_thread(
    thread_id: str,
    user: UserModel = Depends(fetch_user),
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
    user: UserModel = Depends(fetch_user),
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
    user: UserModel = Depends(fetch_user),
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


@app.get("/api/auth/me", response_model=UserModel)
async def auth_me(user: UserModel = Depends(fetch_user)):
    """
    Requires Authorization: Bearer <JWT>
    Forwards the JWT to Resource Watch API and returns user info.
    """

    return user


@app.post("/api/custom_areas/", response_model=CustomAreaModel)
def create_custom_area(
    area: CustomAreaCreate,
    user: UserModel = Depends(fetch_user),
    session=Depends(get_session),
):
    """Create a new custom area for the authenticated user."""
    custom_area = CustomAreaOrm(
        user_id=user.id,
        name=area.name,
        geometries=[i.model_dump_json() for i in area.geometries]
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
    user: UserModel = Depends(fetch_user), session=Depends(get_session)
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
    user: UserModel = Depends(fetch_user),
    session=Depends(get_session),
):
    """Get a specific custom area by ID."""
    custom_area = session.query(CustomAreaOrm).filter_by(id=area_id, user_id=user.id).first()
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
    user: UserModel = Depends(fetch_user),
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
        geometries=[json.loads(i) for i in area.geometries]
    )


@app.delete("/api/custom_areas/{area_id}", status_code=204)
def delete_custom_area(
    area_id: UUID,
    user: UserModel = Depends(fetch_user),
    session=Depends(get_session),
):
    """Delete a custom area."""
    area = session.query(CustomAreaOrm).filter_by(id=area_id, user_id=user.id).first()
    if not area:
        raise HTTPException(status_code=404, detail="Custom area not found")
    session.delete(area)
    session.commit()
