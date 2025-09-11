"""
Core orchestration for E2E testing framework.
"""

import asyncio
import time
from typing import List

import pytest

from .config import get_test_config
from .data_handlers import CSVLoader, ResultExporter
from .langfuse import LangfuseDatasetHandler
from .runners import APITestRunner, LocalTestRunner
from .types import ExpectedData, TestResult


async def run_single_test(
    runner, test_case, test_index, total_tests
) -> TestResult:
    """Run a single test case."""
    start_time = time.time()
    print(
        f"[STARTED] Test {test_index+1}/{total_tests}: {test_case.query[:60]}..."
    )

    # Convert test case to ExpectedData (remove query field)
    expected_data = ExpectedData(
        **{k: v for k, v in test_case.__dict__.items() if k != "query"}
    )
    result = await runner.run_test(test_case.query, expected_data)

    # Print completion with timing
    duration = time.time() - start_time
    score = result.overall_score
    print(
        f"[COMPLETED] Test {test_index+1}/{total_tests}: Score {score:.2f} ({duration:.1f}s)"
    )
    print(
        f"  AOI: {result.aoi_score} | Dataset: {result.dataset_score} | Data: {result.pull_data_score} | Answer: {result.answer_score}"
    )

    return result


async def run_csv_tests(config) -> List[TestResult]:
    """Run E2E tests using CSV data files with parallel execution."""
    print(f"Loading test data from: {config.test_file}")

    # Load test data
    loader = CSVLoader()
    test_cases = loader.load_test_data(
        config.test_file, config.sample_size, config.test_group_filter
    )
    print(
        f"Running {len(test_cases)} tests in {config.test_mode} mode with {config.num_workers} workers..."
    )

    # Setup test runner
    if config.test_mode == "local":
        runner = LocalTestRunner()
    else:
        runner = APITestRunner(
            api_base_url=config.api_base_url, 
            api_token=config.api_token
        )
        print(f"Using API endpoint: {config.api_base_url}")

    # Run tests in parallel
    start_time = time.time()

    if config.num_workers == 1:
        # Sequential execution for single worker
        results = []
        for i, test_case in enumerate(test_cases):
            result = await run_single_test(
                runner, test_case, i, len(test_cases)
            )
            results.append(result)
    else:
        # Parallel execution with semaphore
        semaphore = asyncio.Semaphore(config.num_workers)

        async def run_test_with_semaphore(test_case, test_index):
            async with semaphore:
                return await run_single_test(
                    runner, test_case, test_index, len(test_cases)
                )

        # Create tasks for all tests
        tasks = [
            run_test_with_semaphore(test_case, i)
            for i, test_case in enumerate(test_cases)
        ]

        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks)

    total_duration = time.time() - start_time
    print(f"\nAll tests completed in {total_duration:.1f} seconds")

    # Save results
    exporter = ResultExporter()
    exporter.save_results_to_csv(results, config.output_filename)

    # Print summary
    _print_csv_summary(results, config.test_mode)
    return results


def _print_csv_summary(results: List[TestResult], test_mode: str) -> None:
    """Print CSV test summary statistics."""
    total_tests = len(results)
    if total_tests == 0:
        return

    avg_score = sum(r.overall_score for r in results) / total_tests
    passed = sum(1 for r in results if r.overall_score >= 0.7)

    print(f"\n{'='*50}")
    print(f"SIMPLE E2E TEST SUMMARY ({test_mode.upper()} MODE)")
    print(f"{'='*50}")
    print(f"Total Tests: {total_tests}")
    print(f"Average Score: {avg_score:.2f}")
    print(f"Passed (≥0.7): {passed}/{total_tests} ({passed/total_tests:.1%})")

    # Tool-specific stats
    aoi_avg = sum(r.aoi_score for r in results) / total_tests
    dataset_avg = sum(r.dataset_score for r in results) / total_tests
    data_avg = sum(r.pull_data_score for r in results) / total_tests
    answer_avg = sum(r.answer_score for r in results) / total_tests

    print(f"AOI Selection: {aoi_avg:.2f}")
    print(f"Dataset Selection: {dataset_avg:.2f}")
    print(f"Data Pull: {data_avg:.2f}")
    print(f"Final Answer: {answer_avg:.2f}")


@pytest.mark.asyncio
async def test_e2e():
    """Main E2E test function supporting both CSV and Langfuse modes."""
    # Get configuration
    config = get_test_config()

    if config.is_langfuse_mode():
        # Use Langfuse dataset integration
        handler = LangfuseDatasetHandler(config)
        results = await handler.run_dataset_evaluation(config.langfuse_dataset)
        assert len(results) > 0, "No test results from Langfuse dataset"
    else:
        # Use CSV-based testing
        results = await run_csv_tests(config)
        assert len(results) > 0, "No test results from CSV"


if __name__ == "__main__":
    asyncio.run(test_e2e())
