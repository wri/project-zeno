"""
Langfuse dataset integration for E2E testing framework.
"""

from typing import List

from langfuse.langchain import CallbackHandler

from experiments.eval_utils import get_langfuse, get_run_name

from ..config import TestConfig
from ..runners import APITestRunner, LocalTestRunner
from ..types import ExpectedData, TestResult
from .scoring import LangfuseScorer


class LangfuseDatasetHandler:
    """Handles Langfuse dataset integration for E2E tests."""

    def __init__(self, config: TestConfig):
        """Initialize with test configuration."""
        self.config = config
        self.scorer = LangfuseScorer()

    async def run_dataset_evaluation(
        self, dataset_name: str
    ) -> List[TestResult]:
        """
        Run E2E tests using Langfuse dataset integration.

        Args:
            dataset_name: Name of the Langfuse dataset

        Returns:
            List of test results
        """
        # Setup Langfuse
        langfuse = get_langfuse()
        run_name = get_run_name()
        dataset = langfuse.get_dataset(dataset_name)

        print(
            f"Running E2E evaluation on {len(dataset.items)} items from dataset '{dataset_name}'..."
        )
        print(f"Test mode: {self.config.test_mode}")

        # Setup test runner
        if self.config.test_mode == "local":
            runner = LocalTestRunner()
        else:
            from client import ZenoClient

            client = ZenoClient(
                base_url=self.config.api_base_url, token=self.config.api_token
            )
            runner = APITestRunner(client)
            print(f"Using API endpoint: {self.config.api_base_url}")

        results = []
        for i, item in enumerate(dataset.items):
            if item.metadata.get("status").strip().lower() != "ready":
                continue

            print(f"\nTest {i+1}: {item.input[:60]}...")

            # Prepare expected data from dataset item
            expected_data = ExpectedData(
                expected_aoi_ids=item.metadata.get("expected_aoi_ids", ""),
                expected_aoi_name=item.metadata.get("expected_aoi_name", ""),
                expected_subregion=item.metadata.get("expected_subregion", ""),
                expected_aoi_subtype=item.metadata.get(
                    "expected_aoi_subtype", ""
                ),
                expected_aoi_source=item.metadata.get(
                    "expected_aoi_source", ""
                ),
                expected_dataset_id=item.metadata.get(
                    "expected_dataset_id", ""
                ),
                expected_dataset_name=item.metadata.get(
                    "expected_dataset_name", ""
                ),
                expected_context_layer=item.metadata.get(
                    "expected_context_layer", ""
                ),
                expected_start_date=item.metadata.get(
                    "expected_start_date", ""
                ),
                expected_end_date=item.metadata.get("expected_end_date", ""),
                expected_answer=item.expected_output,  # string
                test_group=item.metadata.get("test_group", "unknown"),
            )

            if self.config.test_mode == "local":
                # Local mode: Use Langfuse dataset integration with handler
                handler = CallbackHandler()

                with item.run(run_name=run_name) as span:
                    # Run the test
                    result = await runner.run_test(
                        item.input, expected_data, handler
                    )

                    # Update trace and add scores
                    span.update_trace(
                        input=item.input,
                        output={
                            "overall_score": result.overall_score,
                            "aoi_score": result.aoi_score,
                            "dataset_score": result.dataset_score,
                            "pull_data_score": result.pull_data_score,
                            "answer_score": result.answer_score,
                            "test_mode": self.config.test_mode,
                        },
                    )

                    # Add scores to span
                    self.scorer.add_scores_to_span(span, result, expected_data)
            else:
                # API mode: Use trace ID to send scores to server-side trace
                result = await runner.run_test(item.input, expected_data)

                # Send evaluation scores to the server-side Langfuse trace
                if result.trace_id:
                    self.scorer.send_scores_to_trace(
                        result.trace_id, result, expected_data
                    )
                else:
                    print("⚠️  No trace ID captured from API response")

            results.append(result)

            # Print quick result
            score = result.overall_score
            print(f"Overall Score: {score:.2f}")
            print(
                f"AOI: {result.aoi_score} | Dataset: {result.dataset_score} | Data: {result.pull_data_score} | Answer: {result.answer_score}"
            )

        # Print summary
        self._print_summary(results, dataset_name, run_name)
        return results

    def _print_summary(
        self, results: List[TestResult], dataset_name: str, run_name: str
    ) -> None:
        """Print test summary statistics."""
        total_tests = len(results)
        if total_tests == 0:
            return

        avg_score = sum(r.overall_score for r in results) / total_tests
        passed = sum(1 for r in results if r.overall_score >= 0.7)

        print(f"\n{'='*50}")
        print(f"E2E TEST SUMMARY ({self.config.test_mode.upper()} MODE)")
        print(f"{'='*50}")
        print(f"Dataset: {dataset_name}")
        print(f"Run Name: {run_name}")
        print(f"Total Tests: {total_tests}")
        print(f"Average Score: {avg_score:.2f}")
        print(
            f"Passed (≥0.7): {passed}/{total_tests} ({passed/total_tests:.1%})"
        )

        # Tool-specific stats
        aoi_avg = sum(r.aoi_score for r in results) / total_tests
        dataset_avg = sum(r.dataset_score for r in results) / total_tests
        data_avg = sum(r.pull_data_score for r in results) / total_tests
        answer_avg = sum(r.answer_score for r in results) / total_tests

        print(f"AOI Selection: {aoi_avg:.2f}")
        print(f"Dataset Selection: {dataset_avg:.2f}")
        print(f"Data Pull: {data_avg:.2f}")
        print(f"Final Answer: {answer_avg:.2f}")
        print(f"\nResults uploaded to Langfuse with run name: {run_name}")
