"""
Core orchestration for E2E testing framework.
"""

import asyncio
from typing import List

from .config import get_test_config
from .data_handlers import CSVLoader, ResultExporter
from .langfuse import LangfuseDatasetHandler
from .runners import APITestRunner, LocalTestRunner
from .types import ExpectedData, TestResult


async def run_csv_tests(config) -> List[TestResult]:
    """Run E2E tests using CSV data files."""
    print(f"Loading test data from: {config.test_file}")

    # Load test data
    loader = CSVLoader()
    test_cases = loader.load_test_data(config.test_file, config.sample_size)
    print(f"Running {len(test_cases)} tests in {config.test_mode} mode...")

    # Setup test runner
    if config.test_mode == "local":
        runner = LocalTestRunner()
    else:
        from client import ZenoClient

        client = ZenoClient(
            base_url=config.api_base_url, token=config.api_token
        )
        runner = APITestRunner(client)
        print(f"Using API endpoint: {config.api_base_url}")

    # Run tests
    results = []
    for i, test_case in enumerate(test_cases):
        print(f"\nTest {i+1}/{len(test_cases)}: {test_case.query[:60]}...")

        # Convert test case to ExpectedData (remove query field)
        expected_data = ExpectedData(
            **{k: v for k, v in test_case.__dict__.items() if k != "query"}
        )
        result = await runner.run_test(test_case.query, expected_data)
        results.append(result)

        # Print quick result
        score = result.overall_score
        print(f"Overall Score: {score:.2f}")
        print(
            f"AOI: {result.aoi_score} | Dataset: {result.dataset_score} | Data: {result.pull_data_score} | Answer: {result.answer_score}"
        )

    # Save results
    exporter = ResultExporter()
    exporter.save_results_to_csv(results)

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
