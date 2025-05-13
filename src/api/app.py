import json
import pdb

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from typing import Dict, List, Any, Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage
from langchain_community.adapters.openai import convert_message_to_dict
from fastapi import HTTPException
import pdb

from src.agents import zeno

app = FastAPI(
    title="Zeno API",
    description="API for Zeno LangGraph-based agent workflow",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

graph = zeno

class ChatRequest(BaseModel):
    query: str = Field(..., description="The query")
    user_persona: Optional[str] = Field(None, description="The user persona")
    thread_id: Optional[str] = Field(None, description="The thread ID")

def pack(data):
    return json.dumps(data) + "\n"

def stream_chat(
    query: str,
    user_persona: Optional[str] = None,
    thread_id: Optional[str] = None,
):
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }
    messages = [HumanMessage(content=query)]

    try:
        stream = graph.stream(
            {
                "messages": messages,
                "user_persona": user_persona,
            },
            config=config,
            stream_mode="updates",
            subgraphs=False,
        )
        for update in stream:
            node = next(iter(update.keys()))

            for msg in update[node]["messages"]:
                yield pack({
                    "node": node,
                    "update": msg.to_json(),
                })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Chat endpoint for Zeno.

    Args:
        request: The chat request

    Returns:
        The streamed response
    """
    try:
        return StreamingResponse(
            stream_chat(
                query=request.query,
                user_persona=request.user_persona,
                thread_id=request.thread_id,
            ),
            media_type="application/x-ndjson",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
