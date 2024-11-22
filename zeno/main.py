from typing import Annotated

from fastapi import FastAPI, Body, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from langfuse.callback import CallbackHandler


from agents.maingraph.agent import graph
from agents.layerfinder.utils.state import GraphState
from agents.maingraph.models import ModelFactory

import json

app = FastAPI()
langfuse_handler = CallbackHandler()


# https://www.softgrade.org/sse-with-fastapi-react-langgraph/
# https://www.workfall.com/learning/blog/how-to-stream-json-data-using-server-sent-events-and-fastapi-in-python-over-http/


def event_stream(query: str, model_id: str):

    initial_state = GraphState(question=query)

    print("MODEL ID: ", model_id)
    for namespace, output in graph.stream(
        initial_state,
        stream_mode="updates",
        subgraphs=True,
        config={
            "configurable": {"model_id": model_id},
            "callbacks": [langfuse_handler],
        },
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
    model_id: Annotated[str, Body(embed=True)] = "llama3.2",
):
    available_models = ModelFactory().available_models
    if not available_models.get(model_id):
        return HTTPException(
            status_code=404,
            detail=f"Model {model_id} not found. Available models: {available_models.keys()}",
        )
    return StreamingResponse(
        event_stream(query, model_id), media_type="application/x-ndjson"
    )


# TODO: add description for ecah model
@app.get("/models")
async def get_models():

    return JSONResponse(
        {
            "models": [
                {"model_id": k, "model_name": v["model_name"]}
                for k, v in ModelFactory().available_models.items()
            ]
        }
    )
