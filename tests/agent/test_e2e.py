"""
Simple end-to-end agent test runner.

Loads test data from CSV, runs agent, and evaluates each step with simple scoring.

USAGE:
    # Run all test cases in the CSV file
    python tests/agent/test_simple_e2e.py

    # Run only first N test cases
    SAMPLE_SIZE=5 python tests/agent/test_simple_e2e.py

ENVIRONMENT VARIABLES:
    SAMPLE_SIZE: Number of test cases to run (default: all rows in CSV)
    TEST_FILE: Path to CSV test file (default: experiments/e2e_test_template.csv)

OUTPUT:
    Creates two CSV files in data/tests/:
    - *_summary.csv: Query and scores only
    - *_detailed.csv: Expected vs actual values side-by-side
"""

import asyncio
import csv
import os
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4

import pandas as pd
import pytest
import structlog
from langfuse.langchain import CallbackHandler

from src.agents.agents import fetch_zeno
from tests.agent.tool_evaluators import (
    evaluate_aoi_selection,
    evaluate_data_pull,
    evaluate_dataset_selection,
    evaluate_final_answer,
)


async def run_agent_test(
    query: str, expected_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Run a single agent test and evaluate results.

    Args:
        query: User query to test
        expected_data: Dict with expected_aoi_id, expected_dataset, expected_answer

    Returns:
        Dict with all evaluation results and scores
    """
    # Setup agent
    agent = await fetch_zeno()

    # Create unique thread
    thread_id = uuid4().hex
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [CallbackHandler()],
        "metadata": {"langfuse_tags": ["simple_e2e_test"]},
    }

    try:
        # Set user_id in structlog context for tools (like the API does)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(user_id="test_user")

        # Run agent
        result = await agent.ainvoke(
            {"messages": [("user", query)], "user_persona": "Researcher"},
            config=config,
        )

        # Get final state
        state = await agent.aget_state(config=config)

        agent_state = state.values

        # Run evaluations
        aoi_eval = evaluate_aoi_selection(
            agent_state,
            expected_data.get("expected_aoi_id", ""),
            expected_data.get("expected_subregion", ""),
        )
        dataset_eval = evaluate_dataset_selection(
            agent_state,
            expected_data.get("expected_dataset_id", ""),
            expected_data.get("expected_context_layer", ""),
        )
        data_eval = evaluate_data_pull(
            agent_state,
            expected_start_date=expected_data.get("start_date", ""),
            expected_end_date=expected_data.get("end_date", ""),
        )
        answer_eval = evaluate_final_answer(
            agent_state, expected_data.get("expected_answer", "")
        )

        # Calculate overall score
        scores = [
            aoi_eval["aoi_score"],
            dataset_eval["dataset_score"],
            data_eval["pull_data_score"],
            answer_eval["answer_score"],
        ]
        overall_score = sum(scores) / len(scores)

        return {
            "thread_id": thread_id,
            "query": query,
            "overall_score": round(overall_score, 2),
            "execution_time": datetime.now().isoformat(),
            **aoi_eval,
            **dataset_eval,
            **data_eval,
            **answer_eval,
            **expected_data,
        }

    except Exception as e:
        # Create complete empty evaluation results to match successful case structure
        empty_eval = {
            # AOI evaluation fields
            "aoi_score": 0,
            "actual_id": None,
            "actual_name": None,
            "actual_subtype": None,
            "actual_source": None,
            "match_aoi_id": False,
            "match_subregion": False,
            # Dataset evaluation fields
            "dataset_score": 0,
            "actual_dataset_id": None,
            "actual_dataset_name": None,
            "actual_context_layer": None,
            # Data pull evaluation fields
            "pull_data_score": 0,
            "row_count": 0,
            "min_rows": 1,
            "data_pull_success": False,
            "date_success": False,
            # Answer evaluation fields
            "answer_score": 0,
            "actual_answer": None,
            # Error field
            "error": str(e),
        }
        return {
            "thread_id": thread_id,
            "query": query,
            "overall_score": 0.0,
            "error": str(e),
            "execution_time": datetime.now().isoformat(),
            **empty_eval,
            **expected_data,
        }


def load_test_data_from_csv(
    csv_file: str, sample_size: int = 0
) -> List[Dict[str, Any]]:
    """Load test data from CSV file - treat everything as strings."""

    # Read CSV as strings and clean up
    df = pd.read_csv(csv_file, dtype=str, keep_default_na=False)

    # Simple cleanup: replace NaN/null with empty string
    df = df.fillna("")

    # Clean all string values
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace(["nan", "NaN", "null", "NULL", "None"], "")

    # Sample if requested (0 means run all rows)
    if sample_size > 0 and sample_size < len(df):
        df = df.sample(n=sample_size)

    test_cases = []
    for _, row in df.iterrows():
        test_cases.append(
            {
                "query": row.get("query", ""),
                "expected_aoi_id": row.get("expected_aoi_id", ""),
                "expected_aoi_name": row.get("expected_aoi_name", ""),
                "expected_subregion": row.get("expected_subregion", ""),
                "expected_aoi_subtype": row.get("expected_aoi_subtype", ""),
                "expected_aoi_source": row.get("expected_aoi_source", ""),
                "expected_dataset_id": row.get("expected_dataset_id", ""),
                "expected_dataset_name": row.get("expected_dataset_name", ""),
                "expected_context_layer": row.get(
                    "expected_context_layer", ""
                ),
                "expected_start_date": row.get("expected_start_date", ""),
                "expected_end_date": row.get("expected_end_date", ""),
                "expected_answer": row.get("expected_answer", ""),
                "test_group": row.get("test_group", "unknown"),
            }
        )

    return test_cases


def save_results_to_csv(
    results: List[Dict[str, Any]], filename: str = None
) -> str:
    """Save test results to two CSV files: summary and detailed."""
    if not results:
        return

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"data/tests/simple_e2e_{timestamp}"
    else:
        base_filename = filename.replace(".csv", "")

    # Create directory if needed
    os.makedirs(os.path.dirname(f"{base_filename}_summary.csv"), exist_ok=True)

    # 1. Summary CSV - just query and scores
    summary_fields = [
        "query",
        "overall_score",
        "aoi_score",
        "dataset_score",
        "pull_data_score",
        "answer_score",
        "execution_time",
        "error",
    ]

    summary_filename = f"{base_filename}_summary.csv"
    with open(summary_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=summary_fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(results)

    # 2. Detailed CSV - expected vs actual side by side
    detailed_fields = [
        # Basic info
        "query",
        "thread_id",
        "overall_score",
        "execution_time",
        # AOI: Expected vs Actual
        "expected_aoi_id",
        "actual_id",
        "aoi_score",
        "match_aoi_id",
        "expected_aoi_name",
        "actual_name",
        "expected_subregion",
        "match_subregion",
        "expected_aoi_subtype",
        "actual_subtype",
        "expected_aoi_source",
        "actual_source",
        # Dataset: Expected vs Actual
        "expected_dataset_id",
        "actual_dataset_id",
        "dataset_score",
        "expected_dataset_name",
        "actual_dataset_name",
        "expected_context_layer",
        "actual_context_layer",
        # Data Pull: Expected vs Actual
        "expected_start_date",
        "actual_start_date",
        "pull_data_score",
        "expected_end_date",
        "actual_end_date",
        "row_count",
        "data_pull_success",
        "date_success",
        # Answer: Expected vs Actual
        "expected_answer",
        "actual_answer",
        "answer_score",
        # Metadata
        "test_group",
        "priority",
        "status",
        "error",
    ]

    detailed_filename = f"{base_filename}_detailed.csv"
    with open(detailed_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=detailed_fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"Summary results saved to: {summary_filename}")
    print(f"Detailed results saved to: {detailed_filename}")
    return summary_filename


@pytest.mark.asyncio
async def test_e2e():
    """Run simple end-to-end tests."""
    # Configuration
    sample_size = int(os.getenv("SAMPLE_SIZE", "0"))  # 0 means run all rows
    test_file = os.getenv("TEST_FILE", "experiments/e2e_test_dataset.csv")

    # Load test data
    print(f"Loading test data from: {test_file}")
    test_cases = load_test_data_from_csv(test_file, sample_size)
    print(f"Running {len(test_cases)} tests...")

    # Run tests
    results = []
    for i, test_case in enumerate(test_cases):
        print(f"\nTest {i+1}/{len(test_cases)}: {test_case['query'][:60]}...")

        result = await run_agent_test(test_case["query"], test_case)
        results.append(result)

        # Print quick result
        score = result.get("overall_score", 0.0)
        print(f"Overall Score: {score:.2f}")
        print(
            f"AOI: {result.get('aoi_score', 0)} | Dataset: {result.get('dataset_score', 0)} | Data: {result.get('pull_data_score', 0)} | Answer: {result.get('answer_score', 0)}"
        )

    # Save results
    filename = save_results_to_csv(results)

    # Print summary
    total_tests = len(results)
    avg_score = sum(r.get("overall_score", 0) for r in results) / total_tests
    passed = sum(1 for r in results if r.get("overall_score", 0) >= 0.7)

    print(f"\n{'='*50}")
    print("SIMPLE E2E TEST SUMMARY")
    print(f"{'='*50}")
    print(f"Total Tests: {total_tests}")
    print(f"Average Score: {avg_score:.2f}")
    print(f"Passed (≥0.7): {passed}/{total_tests} ({passed/total_tests:.1%})")

    # Tool-specific stats
    aoi_avg = sum(r.get("aoi_score", 0) for r in results) / total_tests
    dataset_avg = sum(r.get("dataset_score", 0) for r in results) / total_tests
    data_avg = sum(r.get("pull_data_score", 0) for r in results) / total_tests
    answer_avg = sum(r.get("answer_score", 0) for r in results) / total_tests

    print(f"AOI Selection: {aoi_avg:.2f}")
    print(f"Dataset Selection: {dataset_avg:.2f}")
    print(f"Data Pull: {data_avg:.2f}")
    print(f"Final Answer: {answer_avg:.2f}")

    assert len(results) > 0, "No test results"


if __name__ == "__main__":
    asyncio.run(test_e2e())
