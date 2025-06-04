import os
import subprocess
from datetime import datetime

from langchain_core.load import dumps
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.callback import CallbackHandler

from src.agents import zeno


def get_langfuse():
    """Get Langfuse client."""
    return Langfuse(
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        host=os.getenv("LANGFUSE_HOST"),
    )


def get_run_name():
    """Generate run name with date and git hash."""
    date = datetime.now().strftime("%Y%m%d")
    try:
        git_hash = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .decode()
            .strip()
        )
    except:
        git_hash = "nogit"
    return f"eval_{date}_{git_hash}"


def run_query(
    query: str,
    handler: CallbackHandler,
    user_persona: str = None,
    thread_id: str = None,
):
    """Run a query through Zeno and return JSON response."""
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [handler],
    }

    response = zeno.stream(
        {
            "messages": [HumanMessage(content=query)],
            "user_persona": user_persona,
        },
        config=config,
        stream_mode="updates",
        subgraphs=False,
    )

    return dumps(list(response))
