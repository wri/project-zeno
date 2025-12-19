"""
Base test runner interface for E2E testing framework.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict

from evals.evaluators import (
    evaluate_aoi_selection,
    evaluate_data_pull,
    evaluate_dataset_selection,
    evaluate_final_answer,
)
from evals.utils.eval_types import ExpectedData, TestResult


class BaseTestRunner(ABC):
    """Abstract base class for test runners."""

    @abstractmethod
    async def run_test(
        self, query: str, expected_data: ExpectedData
    ) -> TestResult:
        """
        Run a single E2E test.

        Args:
            query: User query to test
            expected_data: Expected test results for evaluation

        Returns:
            TestResult with evaluation scores and metadata
        """
        pass

    def _create_empty_evaluation_result(
        self,
        thread_id: str,
        trace_url: str,
        query: str,
        expected_data: ExpectedData,
        error: str,
        test_mode: str,
    ) -> TestResult:
        """Create empty evaluation result for error cases."""
        kwargs = expected_data.to_dict()

        kwargs.pop("thread_id", None)
        kwargs.pop("trace_id", None)
        kwargs.pop("trace_url", None)
        kwargs.pop("query", None)
        kwargs.pop("overall_score", None)
        kwargs.pop("execution_time", None)
        kwargs.pop("test_mode", None)

        return TestResult(
            thread_id=thread_id,
            trace_id=None,
            trace_url=trace_url,
            query=query,
            overall_score=0.0,
            execution_time=datetime.now().isoformat(),
            test_mode=test_mode,
            # AOI evaluation fields
            aoi_score=None,
            actual_id=None,
            actual_name=None,
            actual_subtype=None,
            actual_source=None,
            actual_subregion=None,
            match_aoi_id=False,
            match_subregion=False,
            # Dataset evaluation fields
            dataset_score=None,
            actual_dataset_id=None,
            actual_dataset_name=None,
            actual_context_layer=None,
            # Data pull evaluation fields
            pull_data_score=None,
            row_count=0,
            min_rows=1,
            data_pull_success=False,
            date_success=False,
            actual_start_date=None,
            actual_end_date=None,
            # Answer evaluation fields
            answer_score=None,
            actual_answer=None,
            # Expected data
            **kwargs,
            # Error
            error=error,
        )

    def _run_evaluations(
        self,
        agent_state: Dict[str, Any],
        expected_data: ExpectedData,
        query: str = "",
    ) -> Dict[str, Any]:
        """Run all evaluation functions on agent state."""

        aoi_eval = evaluate_aoi_selection(
            agent_state,
            expected_data.expected_aoi_ids,
            expected_data.expected_subregion,
            query,
        )
        dataset_eval = evaluate_dataset_selection(
            agent_state,
            expected_data.expected_dataset_id,
            expected_data.expected_context_layer,
            query,
        )
        data_eval = evaluate_data_pull(
            agent_state,
            expected_start_date=expected_data.expected_start_date,
            expected_end_date=expected_data.expected_end_date,
            query=query,
        )
        answer_eval = evaluate_final_answer(
            agent_state, expected_data.expected_answer
        )

        return {
            **aoi_eval,
            **dataset_eval,
            **data_eval,
            **answer_eval,
        }

    def _calculate_overall_score(
        self, evaluations: Dict[str, Any], expected_data: ExpectedData
    ) -> float:
        """Calculate overall score from individual evaluation scores."""
        scores = []
        if expected_data.expected_aoi_ids:
            scores.append(evaluations["aoi_score"])
        if expected_data.expected_dataset_id:
            scores.append(evaluations["dataset_score"])
            # If a dataset is expected, data pull should also be evaluated
            scores.append(evaluations["pull_data_score"])
        if expected_data.expected_answer:
            scores.append(evaluations["answer_score"])

        if not scores:
            return 0.0

        return round(sum(scores) / len(scores), 2)
