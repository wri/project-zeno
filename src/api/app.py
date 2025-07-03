import os
import json
import cachetools
import requests
from typing import Optional, Dict

from dotenv import load_dotenv
import os

# Load environment variables using shared utility
from src.utils.env_loader import load_environment_variables
load_environment_variables()

from fastapi import FastAPI, HTTPException, Header, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, Field

from langchain_core.load import dumps
from langchain_core.messages import HumanMessage
from langfuse.langchain import CallbackHandler

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.utils.logging_config import get_logger
from src.agents.agents import zeno
from src.api.data_models import UserModel, UserOrm, ThreadModel, ThreadOrm

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

langfuse_handler = CallbackHandler()


class ChatRequest(BaseModel):
    query: str = Field(..., description="The query")
    user_persona: Optional[str] = Field(None, description="The user persona")
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

            for msg in node_data:
                yield pack(
                    {
                        "node": node,
                        "update": msg.to_json(),
                    }
                )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def stream_chat(
    query: str,
    user_persona: Optional[str] = None,
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
    messages = [HumanMessage(content=query)]

    try:
        stream = zeno.stream(
            {
                "messages": messages,
                "user_persona": user_persona,
            },
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


DOMAINS_ALLOWLIST = os.environ.get("DOMAINS_ALLOWLIST", "")
DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
        raise HTTPException(
            status_code=502, detail=f"Error contacting Resource Watch: {e}"
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    user_info = resp.json()

    if isinstance(domains_allowlist, str):
        domains_allowlist = domains_allowlist.split(",")

    if user_info["email"].split("@")[-1].lower() not in domains_allowlist:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not allowed to access this API",
        )

    return UserModel.model_validate(resp.json())


def fetch_user(user_info: UserModel = Depends(fetch_user_from_rw_api)):
    """
    Requires Authorization
    """

    with SessionLocal() as db:
        user = db.query(UserOrm).filter_by(id=user_info.id).first()
        if not user:
            user = UserOrm(**user_info.model_dump())
            db.add(user)
            db.commit()
            db.refresh(user)
        # Convert to Pydantic model while session is open
        return UserModel.model_validate(user)


@app.post("/api/chat")
async def chat(request: ChatRequest): # user: UserModel = Depends(fetch_user)
    """
    Chat endpoint for Zeno.

    Args:
        request: The chat request
        # user: The user, authenticated against the WRI API (injected via FastAPI dependency)

    Returns:
        The streamed response
    """
    # # The following database logic is commented out for testing without auth
    # with SessionLocal() as db:
    #     thread = (
    #         db.query(ThreadOrm).filter_by(id=request.thread_id, user_id=user.id).first()
    #     )
    #     if not thread:
    #         thread = ThreadOrm(
    #             id=request.thread_id, user_id=user.id, agent_id="UniGuana"
    #         )
    #         db.add(thread)
    #         db.commit()
    #         db.refresh(thread)

    try:
        logger.debug(f"Chat request: {request}")
        return StreamingResponse(
            stream_chat(
                query=request.query,
                user_persona=request.user_persona,
                thread_id=request.thread_id,
                metadata=request.metadata,
                session_id=request.session_id,
                user_id=request.user_id,
                tags=request.tags,
            ),
            media_type="application/x-ndjson",
        )
    except Exception as e:
        logger.error(f"Chat request failed: {e}")
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
