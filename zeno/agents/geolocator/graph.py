import os
from uuid import uuid4

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.graph import MessagesState
from langgraph.managed import IsLastStep
from langgraph.managed.is_last_step import RemainingSteps
from langgraph.checkpoint.memory import MemorySaver

from langfuse.callback import CallbackHandler

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
        Find the place & geocode - do not worry about actually answering the user query."""
    )


def main():
    """Main function to demonstrate the location agent functionality."""
    # Create the location agent
    location_agent = create_location_agent()

    # Langfuse tracing
    langfuse_handler = CallbackHandler(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ["LANGFUSE_HOST"],
    )
    
    # Example user query
    user_queries = [
        "find forest fires in Odisha",
        "Show me forest data for congo not drc",
        "What is the deforestation rate in Ontario last year?",
        "I need urgent data on ilegal logging in Borgou!!",
        "How much tree cover has been lost in Sumatera since 2000?"
    ]
    
    for user_query in user_queries:
        # Prepare input and configuration
        agent_inputs = {"messages": [("user", user_query)]}

        agent_config = {
            "configurable": { "thread_id": str(uuid4()) },
            "callbacks": [langfuse_handler],
        }
    
        # Run the agent and print the stream of messages
        print_agent_stream(location_agent.stream(agent_inputs, agent_config, stream_mode="values"))
    
        # Get the final state and extract location information
        final_state = location_agent.get_state(agent_config)
    
        # Extract location details
        location_name = final_state.values["location"].get("location_name", "")
        country = final_state.values["location"].get("country", "")
        region = final_state.values["location"].get("region", "")
    
        # Print the results
        print(f"\nUser Query: {user_query}")
        print(f"Location: {location_name}, {region}, {country}")


# Run the main function if this script is executed directly
if __name__ == "__main__":
    main()