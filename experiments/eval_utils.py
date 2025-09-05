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
    import uuid
    
    # Use a unique thread_id for each evaluation to avoid locking issues
    eval_thread_id = f"eval_{thread_id}_{uuid.uuid4().hex[:8]}"
    
    config = {
        "configurable": {"thread_id": eval_thread_id},  # Unique thread ID
        "callbacks": [handler],
    }

    try:
        print(f"  Creating agent for query: {query[:50]}...")
        zeno_async = await fetch_zeno()

        # Prepare the state updates with the query message
        state_updates = {
            "messages": [HumanMessage(content=query)],
            "user_persona": user_persona,
        }

        print(f"  Starting stream for thread {eval_thread_id}...")
        # Run the agent with the query
        stream = zeno_async.astream(
            state_updates,
            config=config,
            stream_mode="updates",
            subgraphs=False,
        )

        # Consume the stream to ensure the agent completes
        update_count = 0
        async for update in stream:
            update_count += 1
            print(f"    Update {update_count} received")
            
        print(f"  Stream completed with {update_count} updates")

        # Now get the final state after execution
        print(f"  Getting final state...")
        state = await zeno_async.aget_state(config=config)
        print(f"  State retrieved successfully")

        return state

    except langgraph.errors.GraphRecursionError as e:
        # Log the error for debugging
        print(f"GraphRecursionError for query '{query}': {str(e)}")
        # Return None to indicate error
        return None
    except ValueError as e:
        # Handle the specific case of missing ToolMessages
        if "AIMessages with tool_calls that do not have a corresponding ToolMessage" in str(e):
            print(f"Incomplete execution for query '{query}': Tool calls without responses detected")
            # Try to get the state anyway with a different approach
            try:
                # Get the state with snapshot=True to get whatever state is available
                state = await zeno_async.aget_state(config=config, subgraphs=True)
                if state:
                    print(f"  Retrieved partial state for query '{query}'")
                    return state
            except:
                pass
            # If we still can't get the state, return None
            print(f"  Could not retrieve any state for query '{query}'")
            return None
        else:
            # Re-raise other ValueErrors
            raise
    except Exception as e:
        # Catch any other unexpected errors
        print(
            f"Unexpected error for query '{query}': {type(e).__name__}: {str(e)}"
        )
        import traceback
        traceback.print_exc()
        # Return None to indicate error
        return None
