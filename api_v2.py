import json
import uuid
from typing import Annotated, Optional

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import (
    HumanMessage,
)
from langgraph.types import Command

from zeno.agents.zeno.graph import zeno

app = FastAPI()
# # langfuse_handler = CallbackHandler()

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
def event_stream(
    query: str,
    thread_id: Optional[str] = None,
    query_type: Optional[str] = None,
):
    if not thread_id:
        thread_id = str(uuid.uuid4())

    config = {
        # "callbacks": [langfuse_handler],
        "configurable": {"thread_id": thread_id},
    }

    if query_type == "human_input":
        query = HumanMessage(content=query, name="human")
        stream = zeno.stream(
            Command(
                goto="zeno",
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
        stream = zeno.stream(
            {"messages": [query]},
            stream_mode="updates",
            subgraphs=False,
            config=config,
        )
    else:
        raise ValueError(f"Invalid query type from frontend: {query_type}")

    for update in stream:
        node = next(iter(update.keys()))
        # node = list(update.keys())[0]

        if node == "__interrupt__":
            print("INTERRUPTED")
            current_state = zeno.get_state(config)
            yield pack(
                {
                    "node": node,
                    "type": "interrupted",
                    "input": "Do you want to continue?",
                }
            )
        else:
            messages = update[node]["messages"]
            if node == "tools" or node == "tools_with_hil":
                for message in messages:
                    message.pretty_print()
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
                messages.pretty_print()
                yield pack(
                    {
                        "node": node,
                        "type": "update",
                        "content": messages.content,
                    }
                )


@app.post("/stream")
async def stream(
    query: Annotated[str, Body(embed=True)],
    thread_id: Optional[str] = Body(None),
    query_type: Optional[str] = Body(None),
):
    return StreamingResponse(
        event_stream(query, thread_id, query_type),
        media_type="application/x-ndjson",
    )
