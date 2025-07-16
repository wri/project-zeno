import json
import os
import traceback
from typing import Dict, Optional


import cachetools
import requests
import uuid
from datetime import date

# Load environment variables using shared utility
from src.utils.env_loader import load_environment_variables

load_environment_variables()

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi import Request, Response
from itsdangerous import BadSignature, TimestampSigner
from langchain_core.load import dumps
from langchain_core.messages import HumanMessage
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert

from src.agents.agents import zeno, zeno_anonymous
from src.api.data_models import (
    ThreadModel,
    ThreadOrm,
    UserType,
    UserModel,
    UserOrm,
    DailyUsageOrm,
)
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

DOMAINS_ALLOWLIST = os.environ.get("DOMAINS_ALLOWLIST", "")
DATABASE_URL = os.environ["DATABASE_URL"]

# TODO: how to diferentiate between admin and regular users for limits?
# For now, we assume all users are regular users
# Question: will there be only 2 usage tiers? Do we want to set a default
# daily limit and then set custom limits for specific users? (we can use this
# approach to set daily quotas to -1 for unlimited users)
DAILY_QUOTA_WARNING_THRESHOLD = 5
ADMIN_USER_DAILY_QUOTA = 100
REGULAR_USER_DAILY_QUOTA = 25
ANONYMOUS_USER_DAILY_QUOTA = 10
ENABLE_QUOTA_CHECKING = True

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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

    request.state.anonymous_id = signed if need_new else anon_cookie

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
        result = zeno.invoke(None, config=config, subgraphs=False)

        for node, node_data in result.items():
            if node_data is None:
                yield pack({"node": node, "update": "None"})

            elif isinstance(node_data, str):
                yield pack({"node": node, "update": node_data})
            elif isinstance(node_data, dict):
                yield pack({"node": node, "update": json.dumps(node_data)})
            else:
                for msg in node_data:
                    if msg is None:
                        yield pack({"node": node, "update": "None"})
                    elif isinstance(msg, str):
                        yield pack({"node": node, "update": msg})
                    else:
                        yield pack({"node": node, "update": msg.to_json()})

    except Exception as e:
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

    try:
        state_updates["messages"] = messages
        state_updates["user_persona"] = user_persona

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
            node = next(iter(update.keys()))
            yield pack(
                {
                    "node": node,
                    "update": dumps(update[node]),
                }
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# LRU cache for user info, keyed by token
_user_info_cache = cachetools.TTLCache(maxsize=1024, ttl=60 * 60 * 24)  # 1 day


@cachetools.cached(_user_info_cache)
def fetch_user_from_rw_api(
    authorization: Optional[str] = Header(None),
    domains_allowlist: Optional[str] = DOMAINS_ALLOWLIST,
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
        raise HTTPException(
            status_code=502, detail=f"Error contacting Resource Watch: {e}"
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    user_info = resp.json()
    if "name" not in user_info:
        logger.warning(
            "User info does not contain 'name' field, using email account name as fallback"
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


def fetch_user(user_info: Optional[UserModel] = Depends(fetch_user_from_rw_api)):
    """
    Requires Authorization
    """
    if not user_info:
        return None

    with SessionLocal() as db:
        user = db.query(UserOrm).filter_by(id=user_info.id).first()
        if not user:
            user = UserOrm(**user_info.model_dump())
            db.add(user)
            db.commit()
            db.refresh(user)
        # Convert to Pydantic model while session is open
        return UserModel.model_validate(user)


def check_quota(
    request: Request, user: Optional[UserModel] = Depends(fetch_user_from_rw_api)
):

    if not ENABLE_QUOTA_CHECKING:
        return {}

    DAILY_QUOTA = ANONYMOUS_USER_DAILY_QUOTA
    # 1. Get calling user
    if not user:
        if anon := request.cookies.get("anon_id"):
            identity = f"anon:{anon}"
        else:
            identity = f"anon:{request.state.anonymous_id}"

    else:
        print("USER: ", user)
        DAILY_QUOTA = (
            ADMIN_USER_DAILY_QUOTA
            if user.user_type == UserType.ADMIN
            else REGULAR_USER_DAILY_QUOTA
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
    with SessionLocal() as db:
        result = db.execute(stmt)
        count = result.scalar()
        db.commit()  # commit the upsert

    # 3. Enforce the quota
    if count > DAILY_QUOTA:
        raise HTTPException(
            status_code=429,
            detail=f"Daily free limit of {DAILY_QUOTA} exceeded; please try again tomorrow.",
        )

    if count >= DAILY_QUOTA - DAILY_QUOTA_WARNING_THRESHOLD:
        return {
            "warning": f"User {identity} is approaching daily quota limit ({count} prompts out of {DAILY_QUOTA})"
        }

    return {}


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    user: UserModel = Depends(fetch_user),
    quota_info: dict = Depends(check_quota),
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
    if user:
        with SessionLocal() as db:
            thread = (
                db.query(ThreadOrm)
                .filter_by(id=request.thread_id, user_id=user.id)
                .first()
            )
            if not thread:
                thread = ThreadOrm(
                    id=request.thread_id, user_id=user.id, agent_id="UniGuana"
                )
                db.add(thread)
                db.commit()
                db.refresh(thread)
            thread_id = thread.id

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
        logger.error(f"Chat request failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/threads", response_model=list[ThreadModel])
def list_threads(user: UserModel = Depends(fetch_user)):
    """
    Requires Authorization
    """

    with SessionLocal() as db:
        threads = db.query(ThreadOrm).filter_by(user_id=user.id).all()
        return [ThreadModel.model_validate(thread) for thread in threads]


@app.get("/api/threads/{thread_id}")
def get_thread(thread_id: str, user: UserModel = Depends(fetch_user)):
    """
    Requires Authorization
    """

    with SessionLocal() as db:
        thread = db.query(ThreadOrm).filter_by(user_id=user.id, id=thread_id).first()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        thread_id = thread.id

    try:
        logger.debug(f"Replaying thread: {thread_id}")
        return StreamingResponse(
            replay_chat(thread_id=thread_id),
            media_type="application/x-ndjson",
        )
    except Exception as e:
        logger.error(f"Replay failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/me", response_model=UserModel)
async def auth_me(user: UserModel = Depends(fetch_user)):
    """
    Requires Authorization: Bearer <JWT>
    Forwards the JWT to Resource Watch API and returns user info.
    """

    return user
