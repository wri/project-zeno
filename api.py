import json
from typing import Annotated, Optional
import uuid

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langfuse.callback import CallbackHandler
from zeno.agents.maingraph.agent import graph
from zeno.agents.maingraph.utils.state import GraphState
from langchain_core.messages import ToolMessage, AIMessage
app = FastAPI()
langfuse_handler = CallbackHandler()

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
def event_stream(query: str, thread_id: Optional[str]=None):

    if not thread_id:
        thread_id = uuid.uuid4()

    initial_state = GraphState(question=query)

    config = {
        # "callbacks": [langfuse_handler],
        "configurable": {"thread_id": thread_id},
    }

    for namespace, chunk in graph.stream(
    # for data in graph.stream(
        initial_state,
        stream_mode="updates",
        subgraphs=True,
        config=config,
    ):
        node_name = list(chunk.keys())[0]
        print(f"Namespace {namespace}")
        if not namespace:
            continue
        print(f"Node {node_name}")
        if not chunk[node_name]:
            continue
        messages = chunk[node_name].get("messages")
        if not messages:
            continue
        for msg in messages:
            # print(msg)
            # yield pack({
            #     "type": 
            # })
            if isinstance(msg, ToolMessage):
                yield pack({
                    "type": "tool",
                    "tool_name": msg.name,
                    "message": msg.content,
                    "artifact": msg.artifact if hasattr(msg, "artifact") else None,
                })
            elif isinstance(msg, AIMessage):
                if msg.content:
                    yield pack({
                        "type": "assistant",
                        "message": msg.content
                    })



        # node_name = list(chunk.keys())[0]
        # yield pack(chunk[node_name])
        # print(f"Namespace {namespace}")
        # for key, val in data.items():
        #     print(f"Messenger is {key}")
        #     # if key in ["agent", "assistant"]:
        #         # continue
        #     if not val:
        #         continue
        #     for key2, val2 in val.items():
        #         print("Messenger2", key2)
        #         if key2 == "messages":
        #             for msg in val2:
        #                 if msg.content:
        #                     yield pack({"message": msg.content})
        #                 if hasattr(msg, "tool_calls") and msg.tool_calls:
        #                     yield pack({"tool_calls": msg.tool_calls})
        #                 if hasattr(msg, "artifact") and msg.artifact:
        #                     yield pack({"artifact": msg.artifact})
        #         else:
        #             print("NANANA", key, msg)


@app.post("/stream")
async def stream(query: Annotated[str, Body(embed=True)], thread_id: Optional[str]=None):
    return StreamingResponse(event_stream(query, thread_id), media_type="application/x-ndjson")


# Processes the query and returns the response
def process_query(query: str, thread_id: Optional[str]=None):

    if not thread_id:
        thread_id = uuid.uuid4()

    initial_state = GraphState(question=query)

    config = {
        "callbacks": [langfuse_handler],
        "configurable": {"thread_id": thread_id},
    }
    initial_state = GraphState(question=query)
    response = graph.invoke(initial_state, config=config)
    return response


@app.post("/query")
async def query(query: Annotated[str, Body(embed=True)], thread_id: Optional[str]=None):
    return process_query(query, thread_id)
