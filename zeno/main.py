from typing import Annotated

from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from langfuse.callback import CallbackHandler

# from rag.agent import graph
# from rag.utils.models import models
from agents.maingraph.agent import graph
from agents.maingraph.models import models
from agents.layerfinder.utils.state import GraphState

import json

app = FastAPI()
langfuse_handler = CallbackHandler()


# https://www.softgrade.org/sse-with-fastapi-react-langgraph/
# https://www.workfall.com/learning/blog/how-to-stream-json-data-using-server-sent-events-and-fastapi-in-python-over-http/


def event_stream(query: str, model: str):

    initial_state = GraphState(question=query)

    print("MODEL NAME: ", model)
    for namespace, output in graph.stream(
        initial_state,
        stream_mode="updates",
        subgraphs=True,
        config={"configurable": {"model": model}, "callbacks": [langfuse_handler]},
    ):

        for node_name, node_results in output.items():
            for key, data in node_results.items():
                if key == "messages":
                    msg = data[0].content
                    if msg:
                        yield json.dumps({f"{namespace} | {node_name}": msg}) + "\n"


@app.post("/stream")
async def stream(
    query: Annotated[str, Body(embed=True)],
    model: Annotated[str, Body(embed=True)] = "llama32",
):
    if not models.get(model):
        return HTTPException(
            status_code=404,
            detail=f"Model {model} not found. Available models: {models.keys()}",
        )
    return StreamingResponse(
        event_stream(query, model), media_type="application/x-ndjson"
    )


# TODO: add description for ecah model
@app.get("/models")
async def get_models():
    return JSONResponse({"models": list(models.keys())})
