"""Pytest test suite for the pick_dataset tool.

This test suite uses Langfuse to record test results and generate a report as CSV file.

To run the tests, use the following command:

    pytest -s tests/tools/test_pick_dataset.py                  # Run default sample size
    SAMPLE_SIZE=10 pytest -s tests/tools/test_pick_dataset.py   # Run with custom sample size
    SAMPLE_SIZE=all pytest -s tests/tools/test_pick_dataset.py  # Run with all test cases
"""

import os
from uuid import uuid4

import pytest
from langfuse.langchain import CallbackHandler

from src.tools.pick_dataset import pick_dataset
from tests.utils import (
    create_test_agent,
    save_test_results_to_csv,
)

# Simple sample size configuration - change this value or set SAMPLE_SIZE env var
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_TAG = "test_01"


def get_sample_size():
    """Get sample size from environment variable or use default."""
    sample_size = os.getenv("SAMPLE_SIZE", str(DEFAULT_SAMPLE_SIZE))
    return None if sample_size.lower() == "all" else int(sample_size)


def load_test_data(sample_size: int = None):
    """Loads and prepares test data from dataset CSV files."""
    import pandas as pd
    
    base_path = "experiments/"
    files = [
        "Zeno test dataset(S2 T1 Dataset ID).csv",
    ]
    
    try:
        df = pd.concat(
            [pd.read_csv(f"{base_path}{f}") for f in files], ignore_index=True
        )
    except FileNotFoundError as e:
        pytest.skip(f"Test data not found: {e}. Skipping tests.")

    # CSV columns: Q group, Status, Prompt text, Answer (correct data), Does the response match...
    # Filter for ready to run tests only
    df = df[df["Status"] == "ready to run"]
    
    # Drop rows with missing essential data
    df.dropna(subset=["Prompt text", "Answer (correct data)"], inplace=True)
    
    # Simple logic: if sample_size is specified and less than total, sample it
    if sample_size is not None and sample_size < len(df):
        sample = df.sample(n=sample_size)
    else:
        sample = df

    test_cases = []
    for _, row in sample.iterrows():
        query = row["Prompt text"]
        expected_data_type = row["Answer (correct data)"]
        q_group = row.get("Q group", "")

        test_cases.append(
            pytest.param(
                query,
                expected_data_type,
                q_group,
                id=f"q{q_group}_{expected_data_type.replace(' ', '_')}",
            )
        )

    return test_cases


def create_agent():
    """Creates a new agent instance for testing."""
    prompt = """You are a Geo Agent that can ONLY HELP PICK a dataset using the `pick-dataset` tool.
    Pick the best dataset based on the user query. You DONT need to answer the user query, just pick the best dataset."""
    return create_test_agent([pick_dataset], prompt)


AGENT = create_agent()


# Global list to collect test results
test_results = []


@pytest.mark.parametrize(
    "query, expected_data_type, q_group",
    load_test_data(get_sample_size()),
    scope="session",
)
def test_pick_dataset_batch(query, expected_data_type, q_group):
    """Tests the pick_dataset tool on a batch of test cases."""
    config = {
        "configurable": {
            "thread_id": uuid4().hex,
        },
        "callbacks": [CallbackHandler()],
        "metadata": {"langfuse_tags": ["pick_dataset", "test", DEFAULT_TAG]},
    }

    result = AGENT.invoke({"messages": [("user", query)]}, config=config)
    state = AGENT.get_state(config=config)

    dataset = state.values.get("dataset")
    dataset_data_layer = dataset.get("data_layer", "") if dataset else ""
    dataset_source = dataset.get("source", "") if dataset else ""
    dataset_context_layer = dataset.get("context_layer", "") if dataset else ""
    dataset_tile_url = dataset.get("tile_url", "") if dataset else ""
    dataset_daterange = dataset.get("daterange", {}) if dataset else {}
    dataset_threshold = dataset.get("threshold") if dataset else None

    # Score based on whether the selected dataset type matches expected data type
    # This is a simplified scoring - in practice you might want more sophisticated matching
    score = 1 if expected_data_type.lower() in dataset_data_layer.lower() else 0

    # Collect result for CSV export
    test_results.append(
        {
            "query": query,
            "expected_data_type": expected_data_type,
            "q_group": q_group,
            "selected_data_layer": dataset_data_layer,
            "selected_source": dataset_source,
            "selected_context_layer": dataset_context_layer,
            "selected_tile_url": dataset_tile_url,
            "selected_daterange": str(dataset_daterange),
            "selected_threshold": dataset_threshold,
            "score": score,
            "thread_id": config["configurable"]["thread_id"],
        }
    )

    # Basic assertions
    assert dataset is not None, f"No dataset selected for query: {query}"
    assert dataset_data_layer, f"No data layer selected for query: {query}"
    assert dataset_source, f"No source selected for query: {query}"
    assert dataset_tile_url, f"No tile URL selected for query: {query}"


@pytest.fixture(scope="session", autouse=True)
def save_results_after_tests():
    """Automatically save test results after all tests complete.

    This fixture runs before and after all tests in the session.
    The yield statement marks the point where test execution happens.
    After all tests complete, it calls save_test_results_to_csv() to
    export test results to a timestamped CSV file for analysis.
    """
    yield  # This is where the testing happens

    # After all tests complete, save results
    if test_results:
        fieldnames = [
            "query",
            "expected_data_type",
            "q_group",
            "status",
            "selected_data_layer",
            "selected_source",
            "selected_context_layer",
            "selected_tile_url",
            "selected_daterange",
            "selected_threshold",
            "score",
            "thread_id",
        ]
        save_test_results_to_csv(test_results, "pick_dataset", fieldnames)
        print(f"\nSaved {len(test_results)} test results to CSV file.")
    else:
        print("\nNo test results to save.")