from typing import Annotated

from fastapi import FastAPI, Body
from fastapi.responses import Response, StreamingResponse, JSONResponse
from langchain_core.messages import HumanMessage, ToolMessage
from langfuse.callback import CallbackHandler

from rag.agent import graph
import json

app = FastAPI()
langfuse_handler = CallbackHandler()


# https://www.softgrade.org/sse-with-fastapi-react-langgraph/
# https://www.workfall.com/learning/blog/how-to-stream-json-data-using-server-sent-events-and-fastapi-in-python-over-http/


def event_stream(query: str):

    initial_state = {"messages": [HumanMessage(content=query)]}

    for output in graph.stream(initial_state, config={"callbacks": [langfuse_handler]}):
        for node_name, node_results in output.items():
            for message in node_results.get("messages", []):
                if hasattr(message, "content"):
                    # result[node_name] = message.content
                    yield json.dumps({node_name: message.content}) + "\n"


@app.post("/stream")
async def stream(query: Annotated[str, Body(embed=True)]):
    return StreamingResponse(event_stream(query), media_type="application/x-ndjson")
