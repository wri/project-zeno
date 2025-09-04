import os
import subprocess
from datetime import datetime

import langgraph.errors
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from src.agents import fetch_zeno


def get_langfuse():
    """Get Langfuse client."""
    return Langfuse(
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        host=os.getenv("LANGFUSE_HOST"),
    )


def get_run_name():
    """Generate run name with date and git hash."""
    date = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        git_hash = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .decode()
            .strip()
        )
    except:  # noqa: E722
        git_hash = "nogit"
    return f"eval_{date}_{git_hash}"


async def run_query(
    query: str,
    handler: CallbackHandler,
    user_persona: str = None,
    thread_id: str = None,
):
    """Run a query through Zeno and return the final state."""
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [handler],
    }

    try:
        zeno_async = await fetch_zeno()

        # Prepare the state updates with the query message
        state_updates = {
            "messages": [HumanMessage(content=query)],
            "user_persona": user_persona,
        }

        # Run the agent with the query
        stream = zeno_async.astream(
            state_updates,
            config=config,
            stream_mode="updates",
            subgraphs=False,
        )

        # Consume the stream to ensure the agent completes
        async for _ in stream:
            pass  # Just consume the updates

        # Now get the final state after execution
        state = await zeno_async.aget_state(config=config)

        return state

    except langgraph.errors.GraphRecursionError as e:
        # Log the error for debugging
        print(f"GraphRecursionError for query '{query}': {str(e)}")
        # Return None to indicate error
        return None
    except Exception as e:
        # Catch any other unexpected errors
        print(
            f"Unexpected error for query '{query}': {type(e).__name__}: {str(e)}"
        )
        # Return None to indicate error
        return None
