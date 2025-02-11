import io
import json
import os
import uuid
from typing import Annotated, Optional

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from langfuse.callback import CallbackHandler

from zeno.agents.distalert.graph import graph as dist_alert
from zeno.agents.docfinder.graph import graph as docfinder
from zeno.agents.kba.graph import graph as kba
from zeno.agents.layerfinder.graph import graph as layerfinder

load_dotenv()


app = FastAPI()

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


def event_stream_docfinder(
    query: str,
    thread_id: Optional[str] = None,
):
    if not thread_id:
        thread_id = str(uuid.uuid4())

    config = {"configurable": {"thread_id": thread_id}}

    query = HumanMessage(content=query, name="human")
    stream = docfinder.stream(
        {"messages": [query]},
        stream_mode="updates",
        subgraphs=False,
        config=config,
    )

    for update in stream:
        node = next(iter(update.keys()))
        if node == "retrieve":
            continue
        else:
            messages = update[node]["messages"]
            for msg in messages:
                yield pack(
                    {
                        "node": node,
                        "type": "update",
                        "content": msg.content,
                    }
                )


@app.post("/stream/docfinder")
async def stream_docfinder(
    query: Annotated[str, Body(embed=True)],
    thread_id: Optional[str] = Body(None),
):
    return StreamingResponse(
        event_stream_docfinder(query, thread_id),
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
        {"question": query},
        stream_mode="updates",
        subgraphs=False,
        config=config,
    )

    for update in stream:
        node = next(iter(update.keys()))

        if node == "retrieve":
            continue
            # documents = update[node]["documents"]
            # for doc in documents:
            #     yield pack(
            #         {
            #             "node": node,
            #             "type": "update",
            #             "content": doc.page_content,
            #             "metadata": doc.metadata,
            #         }
            #     )
        else:
            messages = update[node]["messages"]
            datasets = json.loads(messages)
            for ds in datasets:
                yield pack(
                    {
                        "node": node,
                        "type": "update",
                        "content": ds,
                    }
                )


@app.post("/stream/layerfinder")
async def stream_layerfinder(
    query: Annotated[str, Body(embed=True)],
    thread_id: Optional[str] = Body(None),
):
    return StreamingResponse(
        event_stream_layerfinder(query, thread_id),
        media_type="application/x-ndjson",
    )


def event_stream_kba(
    query: str,
    user_persona: Optional[str] = None,
    thread_id: Optional[str] = None,
):
    if not thread_id:
        thread_id = str(uuid.uuid4())

    config = {"configurable": {"thread_id": thread_id}}
    query = HumanMessage(content=query, name="human")
    stream = kba.stream(
        {"messages": [query], "user_persona": user_persona},
        stream_mode="updates",
        subgraphs=False,
        config=config,
    )

    for update in stream:
        node = next(iter(update.keys()))

        if node == "kba_response_node":
            print("kba_response_node")
            try:
                report = update[node]["report"].to_dict()
                summary = report["summary"]
                metrics = report["metrics"]
                regional_breakdown = report["regional_breakdown"]
                actions = report["actions"]
                data_gaps = report["data_gaps"]
                yield pack(
                    {
                        "node": node,
                        "type": "report",
                        "summary": summary,
                        "metrics": metrics,
                        "regional_breakdown": regional_breakdown,
                        "actions": actions,
                        "data_gaps": data_gaps,
                    }
                )
            except Exception as e:
                print(e)
        else:
            messages = update[node]["messages"]
            if node == "tools":
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
                for message in messages:
                    yield pack(
                        {
                            "node": node,
                            "type": "update",
                            "content": message.content,
                        }
                    )


@app.post("/stream/kba")
async def stream_kba(
    query: Annotated[str, Body(embed=True)],
    user_persona: Optional[str] = Body(None),
    thread_id: Optional[str] = Body(None),
):
    return StreamingResponse(
        event_stream_kba(query, user_persona, thread_id),
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
