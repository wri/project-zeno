import os
import subprocess
from datetime import datetime
from typing import Type, TypeVar

import langgraph.errors
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel

from src.agents import fetch_zeno

T = TypeVar("T", bound=BaseModel)


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


# This is a workaround for Anthropic+Langchain API's lack of thinking+structured_output
# https://gist.github.com/donbr/aef4488082a0a25c7b829c3bec7445d2
def reason_and_structure(
    prompt: str,
    schema: Type[T],
    reasoning_model: str = "claude-opus-4-1-20250805",
    structuring_model: str = "claude-sonnet-4-20250514",
) -> T:
    """Two-stage process: reason with thinking, then structure the output.

    Args:
        prompt: The prompt to send to the reasoning model
        schema: The Pydantic model or TypedDict to structure the output
        reasoning_model: Model to use for reasoning stage (with thinking)
        structuring_model: Model to use for structuring stage (without thinking)
        thinking_budget: Token budget for thinking in reasoning stage

    Returns:
        Structured output matching the provided schema
    """
    # Stage 1: Reasoning with thinking enabled
    reasoning_llm = ChatAnthropic(
        model=reasoning_model,
        max_tokens=32000,
        thinking={"type": "enabled", "budget_tokens": 20000},
    )

    reasoning_response = reasoning_llm.invoke([HumanMessage(content=prompt)])

    # Stage 2: Structuring with a fast model (no thinking)
    structuring_llm = ChatAnthropic(
        model=structuring_model,
        max_tokens=8000,
        thinking={"type": "disabled"},
    )

    structured_llm = structuring_llm.with_structured_output(schema)

    # Create a prompt that asks the structuring model to extract structured data
    structuring_prompt = f"""Based on the following analysis, provide a structured response.

    Analysis:
    {reasoning_response.content}

    Extract the key information and structure it according to the required format."""

    return structured_llm.invoke([HumanMessage(content=structuring_prompt)])


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
        print("  Getting final state...")
        state = await zeno_async.aget_state(config=config)
        print("  State retrieved successfully")

        return state

    except langgraph.errors.GraphRecursionError as e:
        # Log the error for debugging
        print(f"GraphRecursionError for query '{query}': {str(e)}")
        # Return None to indicate error
        return None
    except ValueError as e:
        # Handle the specific case of missing ToolMessages
        if (
            "AIMessages with tool_calls that do not have a corresponding ToolMessage"
            in str(e)
        ):
            print(
                f"Incomplete execution for query '{query}': Tool calls without responses detected"
            )
            # Try to get the state anyway with a different approach
            try:
                # Get the state with snapshot=True to get whatever state is available
                state = await zeno_async.aget_state(
                    config=config, subgraphs=True
                )
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
