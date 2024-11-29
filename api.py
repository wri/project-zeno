import json
from typing import Annotated

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from langfuse.callback import CallbackHandler
from zeno.agents.maingraph.agent import graph
from zeno.agents.maingraph.utils.state import GraphState

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
def event_stream(query: str):

    initial_state = GraphState(question=query)

    for namespace, data in graph.stream(
        initial_state,
        stream_mode="updates",
        subgraphs=True,
        config={
            "callbacks": [langfuse_handler],
        },
    ):
        print(f"Namespace {namespace}")
        for key, val in data.items():
            print(f"Messenger is {key}")
            if key == "agent":
                continue
            for key2, val2 in val.items():
                if key2 == "messages":
                    for msg in val2:
                        if msg.content:
                            yield pack({"message": msg.content})
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            yield pack({"tool_calls": msg.tool_calls})
                        if hasattr(msg, "artifact") and msg.artifact:
                            yield pack({"artifact": msg.artifact})


@app.post("/stream")
async def stream(query: Annotated[str, Body(embed=True)]):
    return StreamingResponse(event_stream(query), media_type="application/x-ndjson")


# Processes the query and returns the response
def process_query(query: str):
    initial_state = GraphState(question=query)
    response = graph.invoke(initial_state)
    return response


@app.post("/query")
async def query(query: Annotated[str, Body(embed=True)]):
    return process_query(query)
