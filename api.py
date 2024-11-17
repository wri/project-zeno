from typing import Annotated

from fastapi import FastAPI, Body
from fastapi.responses import StreamingResponse
from zeno.agents.maingraph.agent import graph
from zeno.agents.layerfinder.utils.state import GraphState
import json

app = FastAPI()

# https://www.softgrade.org/sse-with-fastapi-react-langgraph/
# https://www.workfall.com/learning/blog/how-to-stream-json-data-using-server-sent-events-and-fastapi-in-python-over-http/

def event_stream(query: str):

    initial_state = GraphState(question=query)

    for namespace, output in graph.stream(initial_state,  stream_mode="updates", subgraphs=True):
        for node_name, node_results in output.items():
            for key, data in node_results.items():
                if key == "messages":
                    msg = data[0].content
                    if msg:
                        yield json.dumps({f"{namespace} | {node_name}": msg}) + "\n"


@app.post("/stream")
async def stream(query: Annotated[str, Body(embed=True)]):
    return StreamingResponse(event_stream(query), media_type="application/x-ndjson")
