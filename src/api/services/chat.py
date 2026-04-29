"""Chat streaming and thread naming services."""

import json
import os
from typing import Dict, Optional

from fastapi import HTTPException
from langchain_core.load import dumps
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from src.agent.graph import fetch_zeno
from src.agent.llms import SMALL_MODEL
from src.api.schemas import ThreadNameOutput
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = os.getenv("STAGE", "production")

langfuse_client = Langfuse()


def pack(data) -> str:
    return json.dumps(data) + "\n"


async def replay_chat(thread_id):
    """
    Fetches an existing thread from Zeno checkpointer (persistent
    memory), and streams the content from each checkpoint, in a
    way that is as close as possible to how the /chat endpoint
    streams updates. Each checkpoint represents a transition from
    one node to the next in the graph's execution, so for each
    checkpoint we will track which elements have already been
    rendered, so as to only include new or updated elements in
    the stream response. Additional, each streamed update will
    contain a thread_id and a checkpoint_id.

    Args:
        thread_id (str): The ID of the thread to replay.
    Returns:
        AsyncGenerator[str, None]: A stream of updates for the specified
        thread. Each update includes the following keys:
            - node : the type of node (e.g. user, system)
            - timestamp : the time at which the update was created
            - update : the actual update content
            - checkpoint_id : the ID of the checkpoint
            - thread_id : the ID of the thread
    """
    config = {"configurable": {"thread_id": thread_id}}

    try:
        zeno_async = await fetch_zeno()

        checkpoints = [
            c async for c in zeno_async.aget_state_history(config=config)
        ]
        checkpoints = sorted(
            list(checkpoints), key=lambda x: x.metadata["step"]
        )
        checkpoints = [c for c in checkpoints if c.metadata["step"] >= 0]

        rendered_state_elements = {"messages": []}

        for checkpoint in checkpoints:
            update = {"messages": []}

            for message in checkpoint.values.get("messages", []):
                if (
                    message.id in rendered_state_elements["messages"]
                    or not message.content
                ):
                    continue
                rendered_state_elements["messages"].append(message.id)
                update["messages"].append(message)

            for key, value in checkpoint.values.items():
                if key == "messages":
                    continue

                if value in rendered_state_elements.setdefault(key, []):
                    continue
                rendered_state_elements[key].append(value)

                update[key] = value

            mtypes = set(m.type for m in update["messages"])

            node_type = (
                "agent"
                if mtypes == {"ai"} or len(mtypes) > 1
                else "tools"
                if mtypes == {"tool"}
                else "human"
            )

            update = {
                "node": node_type,
                "timestamp": checkpoint.created_at,
                "update": dumps(update),
                "checkpoint_id": checkpoint.config["configurable"][
                    "checkpoint_id"
                ],
                "thread_id": checkpoint.config["configurable"]["thread_id"],
            }

            yield pack(update)

    except Exception as e:
        logger.exception("Error during chat replay: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


async def stream_chat(
    query: str,
    user_persona: Optional[str] = None,
    ui_context: Optional[dict] = None,
    ui_action_only: Optional[bool] = False,
    thread_id: Optional[str] = None,
    langfuse_metadata: Optional[Dict] = {},
    user: Optional[dict] = None,
):
    langfuse_handler = CallbackHandler(update_trace=True)
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [langfuse_handler],
        "metadata": langfuse_metadata,
    }

    zeno_async = await fetch_zeno(user)

    messages = []
    ui_action_message = []
    state_updates = {}

    if ui_context:
        for action_type, action_data in ui_context.items():
            match action_type:
                case "aoi_selected":
                    content = f"User selected AOI in UI: {action_data['aoi_name']}\n\n"
                    state_updates["aoi_selection"] = {
                        "aois": [action_data["aoi"]],
                        "name": action_data["aoi_name"],
                    }
                case "dataset_selected":
                    content = f"User selected dataset in UI: {action_data['dataset']['dataset_name']}\n\n"
                    state_updates["dataset"] = action_data["dataset"]
                case "daterange_selected":
                    content = f"User selected daterange in UI: start_date: {action_data['start_date']}, end_date: {action_data['end_date']}"
                    state_updates["start_date"] = action_data["start_date"]
                    state_updates["end_date"] = action_data["end_date"]
                case _:
                    content = f"User performed action in UI: {action_type}\n\n"
            ui_action_message.append(content)

    ui_action_content = "\n".join(ui_action_message).strip()
    if ui_action_content:
        messages.append(HumanMessage(content=ui_action_content))

    if not ui_action_only and query:
        messages.append(HumanMessage(content=query))
    else:
        messages.append(
            HumanMessage(
                content="User performed UI action only. Acknowledge the updates and ask what they would like to do next with their selections."
            )
        )

    state_updates["messages"] = messages
    state_updates["user_persona"] = user_persona

    try:
        stream = zeno_async.astream(
            state_updates,
            config=config,
            stream_mode="updates",
            subgraphs=False,
        )

        async for update in stream:
            try:
                node = next(iter(update.keys()))

                yield pack(
                    {
                        "node": node,
                        "update": dumps(update[node]),
                    }
                )
            except Exception as e:
                logger.exception(
                    "Error processing stream update",
                    error=str(e),
                    update=update,
                )
                yield pack(
                    {
                        "node": "error",
                        "update": dumps(
                            {
                                "error": True,
                                "message": str(e),
                                "error_type": type(e).__name__,
                                "type": "stream_processing_error",
                            }
                        ),
                    }
                )
                continue

        trace_id = getattr(langfuse_handler, "last_trace_id", None)
        if trace_id:
            try:
                trace_url = langfuse_client.get_trace_url(trace_id=trace_id)
            except (AttributeError, Exception) as e:
                logger.warning(
                    "Failed to get trace URL from Langfuse client",
                    error=str(e),
                    trace_id=trace_id,
                )
                trace_url = None

            yield pack(
                {
                    "node": "trace_info",
                    "update": dumps(
                        {"trace_id": trace_id, "trace_url": trace_url}
                    ),
                }
            )

    except Exception as e:
        logger.exception("Error during chat streaming: %s", e)
        yield pack(
            {
                "node": "error",
                "update": dumps(
                    {
                        "error": True,
                        "message": str(e),
                        "error_type": type(e).__name__,
                        "type": "stream_initialization_error",
                        "fatal": True,
                    }
                ),
            }
        )


async def generate_thread_name(query: str) -> str:
    """
    Generate a descriptive name for a chat thread based on the user's query.
    """
    try:
        prompt = f"""Generate a concise, descriptive title (max 50 chars) for a chat conversation that starts with this query:

        QUERY:
        {query}

        RULES:
        - Never include any dates in the name, the user might ask for a date range that is not available.
        """
        response = await SMALL_MODEL.with_structured_output(
            ThreadNameOutput
        ).ainvoke(prompt)
        name = response.name
        if len(name) > 50:
            return name[:47] + "..."
        return name
    except Exception as e:
        logger.exception("Error generating thread name: %s", e)
        return "Unnamed Thread"
