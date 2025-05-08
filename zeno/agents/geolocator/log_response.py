import os
from uuid import uuid4
from dotenv import load_dotenv

from langfuse import Langfuse
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import MessagesState
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from langgraph.checkpoint.memory import MemorySaver
from langfuse.callback import CallbackHandler
from thefuzz import fuzz

from zeno.agents.geolocator.tools import geocode

# Initialize language models with zero temperature for deterministic outputs
CLAUDE_MODEL = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0) 
GPT_MODEL = ChatOpenAI(model="gpt-4o", temperature=0)


class LocationAgentState(MessagesState):
    """State schema for the location agent.
    
    Attributes:
        place: Name of the identified place
        location: Dictionary containing detailed location information
        is_last_step: Flag indicating if this is the last step in the agent's execution
        remaining_steps: Number of remaining steps in the agent's execution
    """
    place: str
    location: dict
    is_last_step: IsLastStep
    remaining_steps: RemainingSteps


def print_agent_stream(stream):
    """Print the messages from an agent's stream output.
    
    Args:
        stream: The stream of messages from the agent
    """
    for step in stream:
        message = step["messages"][-1]
        if isinstance(message, tuple):
            print(message)
        else:
            message.pretty_print()


def create_location_agent():
    """Create and configure a location agent that can geocode places.
    
    Returns:
        Configured location agent
    """
    return create_react_agent(
        GPT_MODEL, 
        tools=[geocode], 
        checkpointer=MemorySaver(), 
        state_schema=LocationAgentState, 
        state_modifier="""You are a Geo Agent that can ONLY HELP GEOCODE a place using the `geocode` tool.
        Find the place & geocode - do not worry about actually answering the user query.
        ONLY geocode a single place from the query, even if the user is asking for multiple places - pick only one.
        """,
    )


def single_query_run(input, langfuse_handler):
    """Run the location agent for a single query."""
    # Create the location agent
    location_agent = create_location_agent()

    # Prepare input and configuration
    agent_inputs = {"messages": [("user", input)]}

    agent_config = {
        "configurable": { "thread_id": str(uuid4()) },
        "callbacks": [langfuse_handler],
    }

    # Run the agent and print the stream of messages
    print_agent_stream(location_agent.stream(agent_inputs, agent_config, stream_mode="values"))

    # Get the final state and extract location information
    final_state = location_agent.get_state(agent_config)

    return final_state.values["place"]

def levenshtein_distance(output, expected_output):
    print("\n\nOutput: ", output)
    print("Expected Output: ", expected_output)
    
    # compute levenshtein distance
    return fuzz.partial_ratio(output, expected_output)

def run_experiment(experiment_name):
    langfuse = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ["LANGFUSE_HOST"],
    )

    ds = langfuse.get_dataset("location-data-test")

    for idx, item in enumerate(ds.items):
        try:
            handler = item.get_langchain_handler(run_name=experiment_name)
            completion = single_query_run(item.input, handler)
            handler.trace.score(
                trace_id=handler.get_trace_id(),
                name="levenshtein_distance",
                value=levenshtein_distance(completion, item.expected_output)
            )
            if idx == 5: # run only 5 queries
                break
        except Exception as e:
            print(f"Error running experiment: {e}")
            continue
    
    langfuse.flush()


# Run the main function if this script is executed directly
if __name__ == "__main__":
    run_experiment("levenstein-distance")