import io
import json
import os
import uuid
from typing import Annotated, Optional

import requests
import cachetools
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import UserOrm
from elevenlabs.client import ElevenLabs
from fastapi import Body, FastAPI, Header, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_community.chat_message_histories import SQLChatMessageHistory
from langgraph.types import Command
from langfuse.callback import CallbackHandler

from zeno.agents.distalert.graph import graph as dist_alert
from zeno.agents.kba.graph import graph as kba
from zeno.agents.layerfinder.graph import graph as layerfinder
from zeno.agents.gfw_data_api.graph import graph as gfw_data_api
from db.models import UserModel, UserOrm, ThreadOrm

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


app = FastAPI()


# LRU cache for user info, keyed by token
_user_info_cache = cachetools.LRUCache(maxsize=1024)


@cachetools.cached(_user_info_cache)
def _fetch_user_info(authorization: str = Header(...)) -> UserModel:

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token"
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
    user_id = user_info.get("id")
    user_name = user_info.get("name") or user_info.get("displayName") or "Unknown"
    user_email = user_info.get("email")

    if not user_id or not user_email:
        raise HTTPException(status_code=500, detail="User info missing id or email")

    with SessionLocal() as db:
        user = db.query(UserOrm).filter_by(id=user_id).first()
        if not user:
            user = UserOrm(
                id=user_id,
                name=user_name,
                email=user_email,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        # Convert to Pydantic model while session is open
        return UserModel.model_validate(user)


@app.get("/auth/me", response_model=UserModel)
async def auth_me(user_info: UserModel = Depends(_fetch_user_info)):
    """
    Requires Authorization: Bearer <JWT>
    Forwards the JWT to Resource Watch API and returns user info.
    """

    return user_info


callbacks = []
if "LANGFUSE_PUBLIC_KEY" in os.environ:
    callbacks.append(CallbackHandler())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def pack(data):
    return json.dumps(data) + "\n"


# Streams the response from the graph
def event_stream_alerts(
    query: str,
    thread_id: Optional[str] = None,
    query_type: Optional[str] = None,
):
    if not thread_id:
        thread_id = str(uuid.uuid4())

    config = {
        "callbacks": callbacks,
        "configurable": {"thread_id": thread_id},
    }

    if query_type == "human_input":
        query = HumanMessage(content=query, name="human")
        stream = dist_alert.stream(
            Command(
                goto="dist_alert",
                update={
                    "messages": [query],
                },
            ),
            stream_mode="updates",
            subgraphs=False,
            config=config,
        )
    elif query_type == "query":
        query = HumanMessage(content=query, name="human")
        stream = dist_alert.stream(
            {"messages": [query]},
            stream_mode="updates",
            subgraphs=False,
            config=config,
        )
    else:
        raise ValueError(f"Invalid query type from frontend: {query_type}")

    for update in stream:
        node = next(iter(update.keys()))

        if node == "__interrupt__":
            print("INTERRUPTED")
            current_state = dist_alert.get_state(config)

            yield pack(
                {
                    "node": node,
                    "type": "interrupted",
                    "input": "Do you want to continue?",
                    "payload": current_state.values["messages"][-1].content,
                }
            )
        else:
            messages = update[node]["messages"]
            if node == "tools" or node == "tools_with_hil":
                for message in messages:
                    yield pack(
                        {
                            "node": node,
                            "type": "tool_call",
                            "tool_name": message.name,
                            "content": message.content,
                            "artifact": (
                                message.artifact
                                if hasattr(message, "artifact")
                                else None
                            ),
                        }
                    )
            else:
                yield pack(
                    {
                        "node": node,
                        "type": "update",
                        "content": messages.content,
                    }
                )


@app.post("/stream/dist_alert")
async def stream_alerts(
    query: Annotated[str, Body(embed=True)],
    thread_id: Optional[str] = Body(None),
    query_type: Optional[str] = Body(None),
):
    return StreamingResponse(
        event_stream_alerts(query, thread_id, query_type),
        media_type="application/x-ndjson",
    )


def event_stream_layerfinder(
    query: str,
    thread_id: Optional[str] = None,
):
    if not thread_id:
        thread_id = str(uuid.uuid4())

    config = {"configurable": {"thread_id": thread_id}}
    stream = layerfinder.stream(
        {"question": query, "messages": [HumanMessage(query)]},
        stream_mode="updates",
        config=config,
    )

    for update in stream:
        node = next(iter(update.keys()))
        if node == "retrieve":
            datasets = update[node]["datasets"]
            for ds in datasets:
                yield pack(
                    {
                        "node": node,
                        "content": ds.model_dump(),
                    }
                )
        elif node == "cautions":
            yield pack(
                {
                    "node": node,
                    "content": update[node]["messages"][0].content,
                }
            )
        elif node == "docfinder":
            yield pack(
                {
                    "node": node,
                    "content": update[node]["messages"][-1].content,
                }
            )
            if "documents" in update[node]:
                documents = update[node]["documents"]
                yield pack(
                    {
                        "node": node,
                        "content": [dict(doc) for doc in documents],
                    }
                )


@app.post("/stream/layerfinder")
async def stream_layerfinder(
    query: Annotated[str, Body(embed=True)],
    thread_id: Optional[str] = Body(None),
):
    return StreamingResponse(
        event_stream_layerfinder(query=query, thread_id=thread_id),
        media_type="application/x-ndjson",
    )


def event_stream_kba(
    query: str,
    user_persona: Optional[str] = None,
    thread_id: Optional[str] = None,
    query_type: Optional[str] = None,
):
    if not thread_id:
        thread_id = str(uuid.uuid4())

    config = {"configurable": {"thread_id": thread_id}}
    if query_type == "human_input":
        query = HumanMessage(content=query, name="human")
        stream = kba.stream(
            Command(
                goto="kba_node",
                update={
                    "messages": [query],
                },
            ),
            stream_mode="updates",
            subgraphs=False,
            config=config,
        )
    elif query_type == "query":
        query = HumanMessage(content=query, name="human")
        stream = kba.stream(
            {"messages": [query], "user_persona": user_persona},
            stream_mode="updates",
            subgraphs=False,
            config=config,
        )
    else:
        raise ValueError(f"Invalid query type from frontend: {query_type}")

    for update in stream:
        node = next(iter(update.keys()))

        if node == "__interrupt__":
            print("INTERRUPTED")
            current_state = kba.get_state(config)
            yield pack(
                {
                    "node": node,
                    "type": "interrupted",
                    "input": "Do you want to continue?",
                    "payload": current_state.values["messages"][-1].content,
                }
            )
        else:
            messages = update[node]["messages"]
            if node == "tools" or node == "tools_with_hil":
                for message in messages:
                    if message.name == "kba-data-tool":
                        yield pack(
                            {
                                "node": node,
                                "type": "tool_call",
                                "tool_name": message.name,
                                "content": message.content,
                                "artifact": (
                                    message.artifact
                                    if hasattr(message, "artifact")
                                    else None
                                ),
                            }
                        )
                    elif message.name == "location-tool":
                        yield pack(
                            {
                                "node": node,
                                "type": "tool_call",
                                "tool_name": message.name,
                                "content": message.content,
                                "artifact": (
                                    message.artifact
                                    if hasattr(message, "artifact")
                                    else None
                                ),
                            }
                        )
                    elif message.name == "kba-insights-tool":
                        current_state = kba.get_state(config)
                        yield pack(
                            {
                                "node": node,
                                "type": "tool_call",
                                "tool_name": message.name,
                                "content": message.content,
                                "dataset": current_state.values["kba_within_aoi"],
                            }
                        )
                    else:
                        yield pack(
                            {
                                "node": node,
                                "type": "tool_call",
                                "tool_name": message.name,
                                "content": message.content,
                                "artifact": None,
                            }
                        )
            else:
                # Check if previous tool call is kba-insights-tool, add a summary boolean
                current_state = kba.get_state(config)
                summary = False
                if len(current_state.values["messages"]) >= 2:
                    previous_tool_call = current_state.values["messages"][-2]
                    summary = (
                        previous_tool_call.name == "kba-insights-tool"
                        or previous_tool_call.name == "kba-timeseries-tool"
                    )

                for message in messages:
                    yield pack(
                        {
                            "node": node,
                            "type": "update",
                            "content": message.content,
                            "summary": summary,
                        }
                    )


@app.post("/stream/kba")
async def stream_kba(
    query: Annotated[str, Body(embed=True)],
    user_persona: Optional[str] = Body(None),
    thread_id: Optional[str] = Body(None),
    query_type: Optional[str] = Body(None),
):
    return StreamingResponse(
        event_stream_kba(query, user_persona, thread_id, query_type),
        media_type="application/x-ndjson",
    )


def event_stream_gfw_data_api(
    query: str,
    user_id: str,
    thread_id: Optional[str] = None,
    query_type: Optional[str] = None,
):

    if not thread_id:
        thread_id = str(uuid.uuid4())

    config = {"configurable": {"thread_id": thread_id}}
    stream = gfw_data_api.stream(
        {"question": query, "messages": [HumanMessage(query)]},
        stream_mode="updates",
        config=config,
    )

    if query_type == "human_input":
        query = HumanMessage(content=query, name="human")
        stream = gfw_data_api.stream(
            Command(
                goto="gfw_data_api",
                update={
                    "messages": [query],
                },
            ),
            stream_mode="updates",
            subgraphs=False,
            config=config,
        )
    elif query_type == "query":
        query = HumanMessage(content=query, name="human")
        stream = gfw_data_api.stream(
            {"messages": [query]},
            stream_mode="updates",
            subgraphs=False,
            config=config,
        )
    else:
        raise ValueError(f"Invalid query type from frontend: {query_type}")

    # Stores the stream to later write to the database
    messages_store = []

    for update in stream:

        node = next(iter(update.keys()))

        if node == "__interrupt__":
            print("INTERRUPTED")
            current_state = gfw_data_api.get_state(config)

            yield pack(
                {
                    "node": node,
                    "type": "interrupted",
                    "input": "Do you want to continue?",
                    "payload": current_state.values["messages"][-1].content,
                }
            )
        else:
            messages = update[node]["messages"]

            if node == "tools" or node == "tools_with_hil":
                for message in messages:
                    yield pack(
                        {
                            "node": node,
                            "type": "tool_call",
                            "tool_name": message.name,
                            "content": message.content,
                            "artifact": (
                                message.artifact
                                if hasattr(message, "artifact")
                                else None
                            ),
                        }
                    )
            else:
                yield pack(
                    {
                        "node": node,
                        "type": "update",
                        "content": messages.content,
                    }
                )

    messages_to_store = gfw_data_api.get_state(config).values["messages"]
    # import logging

    # logging.error(messages_to_store)
    # logging.error([message.dict() for message in messages_to_store])

    # Write the stream to the database
    with SessionLocal() as db:
        existing_thread = db.query(ThreadOrm).filter_by(id=thread_id).first()
        new_responses = [message.dict() for message in messages_to_store]
        if existing_thread:
            # Append new messages to the "response" field in content
            if "response" in existing_thread.content and isinstance(
                existing_thread.content["response"], list
            ):
                existing_thread.content["response"].extend(new_responses)
            else:
                existing_thread.content["response"] = new_responses
            db.commit()
            db.refresh(existing_thread)
        else:
            thread = ThreadOrm(
                id=thread_id,
                user_id=user_id,
                content={
                    "query": query.dict(),
                    "response": new_responses,
                },
            )
            db.add(thread)
            db.commit()
            db.refresh(thread)


@app.post("/stream/gfw_data_api")
async def stream_gfw_data_api(
    query: Annotated[str, Body(embed=True)],
    thread_id: Optional[str] = Body(None),
    query_type: Optional[str] = Body(None),
    user_info: UserModel = Depends(_fetch_user_info),
):

    return StreamingResponse(
        event_stream_gfw_data_api(
            query=query,
            user_id=user_info.id,
            thread_id=thread_id,
            query_type=query_type,
        ),
        media_type="application/x-ndjson",
    )


@app.get("/stream/voice")
async def stream_audio(query: str):
    client = ElevenLabs(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
    )

    audio = client.text_to_speech.convert(
        text=query,
        voice_id="MKOHthhn22dKT5XpmFBl",
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    audio_buffer = io.BytesIO()
    for chunk in audio:
        if chunk:
            audio_buffer.write(chunk)
    audio_buffer.seek(0)

    return Response(content=audio_buffer.getvalue(), media_type="audio/mpeg")
