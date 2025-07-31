"""Pytest test suite for the pick_aoi tool.

This test suite uses Langfuse to record test results and generate a report as CSV file.

To run the tests, use the following command:

    pytest -s tests/tools/test_pick_aoi.py                  # Run default sample size
    SAMPLE_SIZE=10 pytest -s tests/tools/test_pick_aoi.py   # Run with custom sample size
    SAMPLE_SIZE=all pytest -s tests/tools/test_pick_aoi.py  # Run with all test cases
"""

import os
from uuid import uuid4

import pytest
from langfuse.langchain import CallbackHandler

from src.utils.geocoding_helpers import GADM_LEVELS
from src.tools.pick_aoi import pick_aoi
from tests.utils import (
    create_test_agent,
    load_test_data_from_csv,
    save_test_results_to_csv,
)

# Simple sample size configuration - change this value or set SAMPLE_SIZE env var
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_TAG = "test_01"


def normalize_gadm_id(gadm_id: str) -> str:
    gadm_id = gadm_id.split("_")[0].replace("-", ".").lower()
    return gadm_id


def get_sample_size():
    """Get sample size from environment variable or use default."""
    sample_size = os.getenv("SAMPLE_SIZE", str(DEFAULT_SAMPLE_SIZE))
    return None if sample_size.lower() == "all" else int(sample_size)


def load_test_data(sample_size: int = None):
    """Loads and prepares test data from multiple CSV files."""
    base_path = "experiments/"
    files = [
        "Zeno test dataset(S2 GADM 0-1).csv",
        "Zeno test dataset(S2 GADM 2).csv",
        "Zeno test dataset(S2 GADM 3).csv",
        "Zeno test dataset(S2 GADM 4).csv",
    ]
    return load_test_data_from_csv(base_path, files, sample_size)


def create_agent():
    """Creates a new agent instance for testing."""
    prompt = """You are a Geo Agent that can ONLY HELP PICK an AOI using the `pick-aoi` tool.
    Pick the best AOI based on the user query. You DONT need to answer the user query, just pick the best AOI."""
    return create_test_agent([pick_aoi], prompt)


AGENT = create_agent()


# Global list to collect test results
test_results = []


@pytest.mark.parametrize(
    "query, expected_id, expected_name, expected_type",
    load_test_data(get_sample_size()),
    scope="session",
)
def test_pick_aoi_batch(query, expected_id, expected_name, expected_type):
    """Tests the pick_aoi tool on a batch of test cases."""
    config = {
        "configurable": {
            "thread_id": uuid4().hex,
        },
        "callbacks": [CallbackHandler()],
        "metadata": {"langfuse_tags": ["pick_aoi", "test", DEFAULT_TAG]},
    }

    result = AGENT.invoke({"messages": [("user", query)]}, config=config)
    state = AGENT.get_state(config=config)

    aoi = state.values.get("aoi")
    subtype = state.values.get("subtype")
    gadm_level = GADM_LEVELS[subtype]
    aoi_gadm_id = aoi.get(gadm_level["col_name"]) if aoi else None
    aoi_name = aoi.get("name", "") if aoi else ""
    aoi_subtype = aoi.get("subtype", "") if aoi else ""

    score = 1 if normalize_gadm_id(aoi_gadm_id) == normalize_gadm_id(expected_id) else 0

    # Collect result for CSV export
    test_results.append(
        {
            "query": query,
            "expected_id": expected_id,
            "expected_name": expected_name,
            "expected_type": expected_type,
            "actual_id": aoi_gadm_id,
            "actual_name": aoi_name,
            "actual_type": aoi_subtype,
            "score": score,
        }
    )

    # Individual assertion for each test case
    assert normalize_gadm_id(aoi_gadm_id) == normalize_gadm_id(expected_id), (
        f"For query '{query}', agent picked {aoi_gadm_id} (name: {aoi_name}) "
        f"but expected id: {expected_id} (name: {expected_name})."
    )


@pytest.fixture(scope="session", autouse=True)
def save_results_after_tests():
    """Automatically save test results after all tests complete.

    This fixture runs before and after all tests in the session.
    The yield statement marks the point where test execution happens.
    After all tests complete, it calls save_test_results_to_csv() to
    export test results to a timestamped CSV file for analysis.
    """
    yield  # This runs after all tests

    # Save results using the utility function
    fieldnames = [
        "query",
        "expected_id",
        "expected_name",
        "expected_type",
        "actual_id",
        "actual_name",
        "actual_type",
        "score",
    ]
    save_test_results_to_csv(test_results, "pick_aoi", fieldnames)
