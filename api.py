import json
from typing import Annotated

from fastapi import Body, FastAPI
from fastapi.responses import StreamingResponse

from zeno.agents.maingraph.utils.state import GraphState
from zeno.agents.maingraph.agent import graph

app = FastAPI()

# https://www.softgrade.org/sse-with-fastapi-react-langgraph/
# https://www.workfall.com/learning/blog/how-to-stream-json-data-using-server-sent-events-and-fastapi-in-python-over-http/


def pack(data):
    return json.dumps(data) + "\n"


# Streams the response from the graph
def event_stream(query: str):

    initial_state = GraphState(question=query)

    for namespace, data in graph.stream(
        initial_state, stream_mode="updates", subgraphs=True
    ):
        print(f"Namespace {namespace}")
        for key, val in data.items():
            print(f"Messager is {key}")
            for key2, val2 in val.items():
                if key2 == "messages":
                    for msg in val.get("messages", []):
                        yield pack({"message": msg.content})
                        if hasattr(msg, "tool_calls"):
                            yield pack({"tool_calls": msg.tool_calls})
                        if hasattr(msg, "artifact"):
                            yield pack({"artifact": msg.artifact})
                else:
                    yield pack({key2: val2})


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
