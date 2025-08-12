import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

import geopandas as gpd
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

load_dotenv()


# Connection Manager for WebSocket clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.thread_states: Dict[str, Any] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.thread_states:
            del self.thread_states[client_id]

    async def send_message(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

    def set_thread_state(self, client_id: str, state: Any):
        self.thread_states[client_id] = state

    def get_thread_state(self, client_id: str) -> Optional[Any]:
        return self.thread_states.get(client_id)


class MessageType(str, Enum):
    QUERY = "query"
    HUMAN_INPUT = "human_input"
    RESULT = "result"
    ERROR = "error"


@dataclass
class WebSocketMessage:
    type: MessageType
    content: dict
    client_id: str


app = FastAPI()


@app.get("/")
def serve_root():
    with open("frontend/index.html") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)


manager = ConnectionManager()

# llm = ChatAnthropic(model="claude-3-5-sonnet-20240620")
llm = ChatOllama(model="qwen2.5:7b")


@tool
def location(query: str):
    "Returns location of a place"
    match_df = gpd.read_file(
        "data/gadm_410_small.gpkg", where=f"name like '%{query}%'"
    )
    return match_df.to_json()


@tool
def weather(query: str):
    "Retuns weather of a place"
    return f"The weather of {query} is hot & humid."


tools = [location, weather]
llm = llm.bind_tools(tools)


def should_continue(state):
    last_msg = state["messages"][-1]
    if not last_msg.tool_calls:
        return "end"
    else:
        return "continue"


def call_model(state):
    msgs = state["messages"]
    r = llm.invoke(msgs)
    return {"messages": [r]}


# Setup LangGraph workflow
tool_node = ToolNode(tools)
wf = StateGraph(MessagesState)

wf.add_node("agent", call_model)
wf.add_node("action", tool_node)

wf.add_edge(START, "agent")
wf.add_conditional_edges(
    "agent", should_continue, {"end": END, "continue": "action"}
)
wf.add_edge("action", "agent")

memory = MemorySaver()
graph = wf.compile(checkpointer=memory, interrupt_after=["action"])


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
                message = WebSocketMessage(**data)

                if message.type == MessageType.QUERY:
                    # Initialize new graph execution
                    thread = {"configurable": {"thread_id": client_id}}
                    inputs = [HumanMessage(content=message.content["query"])]

                    try:
                        async for event in graph.astream(
                            {"messages": inputs}, thread, stream_mode="values"
                        ):
                            last_message = event["messages"][-1]

                            if isinstance(last_message, ToolMessage):
                                # Store current state for HITL
                                manager.set_thread_state(
                                    client_id,
                                    {
                                        "thread": thread,
                                        "tool_message": last_message,
                                    },
                                )

                                # If it's a location tool, send options to client
                                if last_message.name == "location":
                                    options = gpd.read_file(
                                        last_message.content, driver="GeoJSON"
                                    )
                                    locations = [
                                        {"id": idx, "name": row["name"]}
                                        for idx, row in options.iterrows()
                                    ]
                                    await manager.send_message(
                                        client_id,
                                        {
                                            "type": "options",
                                            "tool": "location",
                                            "options": locations,
                                        },
                                    )
                                    break  # Wait for human input

                            await manager.send_message(
                                client_id,
                                {
                                    "type": "update",
                                    "content": last_message.content,
                                },
                            )

                    except Exception as e:
                        await manager.send_message(
                            client_id, {"type": "error", "content": str(e)}
                        )

                elif message.type == MessageType.HUMAN_INPUT:
                    # Handle human input and continue graph execution
                    thread_state = manager.get_thread_state(client_id)
                    if not thread_state:
                        await manager.send_message(
                            client_id,
                            {
                                "type": "error",
                                "content": "No active state found",
                            },
                        )
                        continue

                    tool_message = thread_state["tool_message"]
                    thread = thread_state["thread"]

                    if tool_message.name == "location":
                        selected_idx = message.content["selected_index"]
                        options = gpd.read_file(
                            tool_message.content, driver="GeoJSON"
                        )
                        selected_row = options.iloc[selected_idx]

                        # Update the tool message content
                        tool_message.content = f"{selected_row['name']} is located in south east india, in Odisha."
                        graph.update_state(thread, {"messages": tool_message})

                        # Send map update - selected_row is a GeoDataFrame row with geometry
                        geometry = selected_row.geometry.__geo_interface__

                        geojson_feature = {
                            "type": "Feature",
                            "properties": {
                                "name": selected_row[
                                    "name"
                                ]  # or any attributes you want
                            },
                            "geometry": geometry,
                        }
                        # geojson_feature = json.loads(selected_row.geometry.to_json())
                        await manager.send_message(
                            client_id,
                            {"type": "map_update", "geojson": geojson_feature},
                        )

                    # Continue graph execution
                    async for event in graph.astream(
                        None, thread, stream_mode="values"
                    ):
                        last_message = event["messages"][-1]
                        await manager.send_message(
                            client_id,
                            {
                                "type": "update",
                                "content": last_message.content,
                            },
                        )

            except json.JSONDecodeError:
                await manager.send_message(
                    client_id,
                    {"type": "error", "content": "Invalid JSON message"},
                )
            except Exception as e:
                await manager.send_message(
                    client_id, {"type": "error", "content": str(e)}
                )

    except WebSocketDisconnect:
        manager.disconnect(client_id)
