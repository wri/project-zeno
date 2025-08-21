import csv
import os
import subprocess
from datetime import datetime

import pandas as pd
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

from src.graph.state import AgentState
from src.utils.env_loader import load_environment_variables
from src.utils.llms import GEMINI

load_environment_variables()


def get_run_name():
    """Generate run name with date and git hash."""
    date = datetime.now().strftime("%Y%m%d_%H%M")
    try:
        git_hash = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .decode()
            .strip()
        )
    except:  # noqa: E722
        git_hash = "nogit"
    return f"{date}_{git_hash}"


def load_test_data_from_csv(
    base_path: str, files: list, sample_size: int = None
):
    """Loads and prepares test data from multiple CSV files.

    Args:
        base_path: Base directory path for CSV files
        files: List of CSV filenames to load
        sample_size: Number of samples to return (None for all, default=None)

    Returns:
        List of test case tuples
    """
    try:
        df = pd.concat(
            [pd.read_csv(f"{base_path}{f}") for f in files], ignore_index=True
        )
    except FileNotFoundError as e:
        pytest.skip(f"Test data not found: {e}. Skipping tests.")

    df.dropna(subset=["text", "id", "name", "type"], inplace=True)

    # Simple logic: if sample_size is specified and less than total, sample it
    if sample_size is not None and sample_size < len(df):
        sample = df.sample(n=sample_size)
    else:
        sample = df

    test_cases = []
    for _, row in sample.iterrows():
        # Skip test cases with multiple expected AOIs for now
        if ";" in str(row["id"]):
            continue

        query = row["text"]
        expected_id = row["id"]
        expected_name = row["name"]
        expected_type = row["type"]

        test_cases.append(
            pytest.param(
                query,
                expected_id,
                expected_name,
                expected_type,
                id=f"{row['id']}",
            )
        )
    return test_cases


def create_test_agent(tools: list, prompt: str = None):
    """Creates a new agent instance for testing.

    Args:
        tools: List of tools to provide to the agent
        prompt: Custom prompt for the agent

    Returns:
        Configured agent instance
    """
    default_prompt = """You are a test agent that can help with various tasks using the provided tools."""

    return create_react_agent(
        GEMINI,
        tools=tools,
        state_schema=AgentState,
        checkpointer=InMemorySaver(),
        prompt=prompt or default_prompt,
    )


def save_test_results_to_csv(
    test_results: list, test_name: str, fieldnames: list
):
    """Save test results to CSV file.

    Args:
        test_results: List of test result dictionaries
        test_name: Name of the test (used in filename)
        fieldnames: List of CSV column names
    """
    if not test_results:
        return

    # Create directory if it doesn't exist
    run_name = get_run_name()
    output_dir = f"data/tests/{test_name}"
    os.makedirs(output_dir, exist_ok=True)

    # Generate filename with run name
    filename = f"{output_dir}/{run_name}.csv"

    # Write results to CSV
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for result in test_results:
            writer.writerow(result)

    print(f"Test results saved to: {filename}")
    return filename
