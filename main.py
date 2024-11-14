from typing import Annotated

from fastapi import FastAPI, Body
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, ToolMessage
from rag.agent import graph


app = FastAPI()

# https://www.softgrade.org/sse-with-fastapi-react-langgraph/


def event_stream(query: str):
    initial_state = {"messages": [HumanMessage(content=query)]}
    for output in graph.stream(initial_state):
        print(output)
        for node_name, node_results in output.items():
            yield f"---Output from {node_name}---"
            chunk_messages = node_results.get("messages", [])
            for message in chunk_messages:
                if hasattr(message, "content"):
                    print(message.content)
                    yield message.content


@app.post("/stream")
async def stream(query: Annotated[str, Body(embed=True)]):
    return StreamingResponse(event_stream(query), media_type="text/event-stream")
