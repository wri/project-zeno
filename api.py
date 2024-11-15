from typing import Annotated

from fastapi import FastAPI, Body
from fastapi.responses import Response, StreamingResponse, JSONResponse
from langchain_core.messages import HumanMessage, ToolMessage
# from zeno.agents.docfinder.agent import graph
from zeno.agents.layerfinder.agent import graph
from zeno.agents.layerfinder.utils.state import GraphState
import json

app = FastAPI()

# https://www.softgrade.org/sse-with-fastapi-react-langgraph/
# https://www.workfall.com/learning/blog/how-to-stream-json-data-using-server-sent-events-and-fastapi-in-python-over-http/

def event_stream(query: str):

    initial_state = GraphState(question=query)

    for output in graph.stream(initial_state):
        for node_name, node_results in output.items():
            for key, data in node_results.items():
                if hasattr(data, "content"):
                    yield json.dumps({node_name: data.content}) + "\n"
                else:
                    yield json.dumps({node_name: str(data)}) + "\n"


@app.post("/stream")
async def stream(query: Annotated[str, Body(embed=True)]):
    return StreamingResponse(event_stream(query), media_type="application/x-ndjson")
