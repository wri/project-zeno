"""Pytest test suite for the pick_aoi tool."""

from uuid import uuid4

import pytest
import pandas as pd
from dotenv import load_dotenv
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
from langchain_anthropic import ChatAnthropic

from src.graph.state import AgentState
from src.tools.pick_aoi import pick_aoi, CLAUDE_MODEL
from src.tools.pull_data import gadm_levels

# Load environment variables from .env file
load_dotenv()


def load_test_data(sample_size: int = 10):
    """Loads and prepares test data from multiple CSV files."""
    base_path = "experiments/"
    files = [
        "Zeno test dataset(S2 GADM 0-1).csv",
        "Zeno test dataset(S2 GADM 2).csv",
        "Zeno test dataset(S2 GADM 3).csv",
        "Zeno test dataset(S2 GADM 4).csv",
    ]
    try:
        df = pd.concat(
            [pd.read_csv(f"{base_path}{f}") for f in files], ignore_index=True
        )
    except FileNotFoundError as e:
        pytest.skip(f"Test data not found: {e}. Skipping AOI tests.")

    df.dropna(subset=["text", "id", "name", "type"], inplace=True)
    sample = df.sample(n=sample_size)

    test_cases = []
    for _, row in sample.iterrows():
        # Skip test cases with multiple expected AOIs for now
        if ";" in str(row["id"]):
            continue

        query = row["text"]
        expected_id = row["id"]
        expected_type = row["type"]

        # Map CSV type to a pytest marker
        marker_map = {
            "iso": "gadm_0",
            "adm1": "gadm_1",
            "adm2": "gadm_2",
            "adm3": "gadm_3",
            "adm4": "gadm_4",
            "wdpa": "wdpa",
        }
        marker_name = marker_map.get(str(expected_type).lower(), "other")
        marker = getattr(pytest.mark, marker_name)

        test_cases.append(
            pytest.param(
                query,
                expected_id,
                expected_type,
                marks=marker,
                id=f"{marker_name}-{row['name'][:20]}",
            )
        )
    return test_cases


def create_agent():
    """Creates a new agent instance for testing."""
    return create_react_agent(
        CLAUDE_MODEL,
        tools=[pick_aoi],
        state_schema=AgentState,
        checkpointer=InMemorySaver(),
        prompt="""You are a Geo Agent that can ONLY HELP PICK an AOI using the `pick-aoi` tool.
        Pick the best AOI based on the user query. You DONT need to answer the user query, just pick the best AOI.""",
    )


AGENT = create_agent()


@pytest.mark.parametrize("query, expected_id, expected_type", load_test_data())
def test_pick_aoi(query, expected_id, expected_type):
    """Tests the pick_aoi tool to ensure it selects the correct AOI."""
    config = {
        "configurable": {
            "thread_id": uuid4().hex,
        }
    }
    
    result = AGENT.invoke({"messages": [( "user", query)]}, config=config)
    state = AGENT.get_state(config=config)

    aoi = state.values.get("aoi")
    subtype = state.values.get("subtype")
    gadm_level = gadm_levels[subtype]
    aoi_gadm_id = aoi.get(gadm_level['col_name'])

    assert aoi_gadm_id == expected_id, (
        f"For query '{query}', agent picked {aoi_gadm_id} (name: {aoi.get('name')}) "
        f"but expected {expected_id}."
    )
