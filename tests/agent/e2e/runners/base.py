"""
Base test runner interface for E2E testing framework.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from ..types import ExpectedData, TestResult


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
        query: str,
        expected_data: ExpectedData,
        error: str,
        test_mode: str,
    ) -> TestResult:
        """Create empty evaluation result for error cases."""
        from datetime import datetime

        return TestResult(
            thread_id=thread_id,
            trace_id=None,
            query=query,
            overall_score=0.0,
            execution_time=datetime.now().isoformat(),
            test_mode=test_mode,
            # AOI evaluation fields
            aoi_score=0,
            actual_id=None,
            actual_name=None,
            actual_subtype=None,
            actual_source=None,
            match_aoi_id=False,
            match_subregion=False,
            # Dataset evaluation fields
            dataset_score=0,
            actual_dataset_id=None,
            actual_dataset_name=None,
            actual_context_layer=None,
            # Data pull evaluation fields
            pull_data_score=0,
            row_count=0,
            min_rows=1,
            data_pull_success=False,
            date_success=False,
            actual_start_date=None,
            actual_end_date=None,
            # Answer evaluation fields
            answer_score=0,
            actual_answer=None,
            # Expected data
            **expected_data.to_dict(),
            # Error
            error=error,
        )

    def _run_evaluations(
        self, agent_state: Dict[str, Any], expected_data: ExpectedData
    ) -> Dict[str, Any]:
        """Run all evaluation functions on agent state."""
        from tests.agent.tool_evaluators import (
            evaluate_aoi_selection,
            evaluate_data_pull,
            evaluate_dataset_selection,
            evaluate_final_answer,
        )

        aoi_eval = evaluate_aoi_selection(
            agent_state,
            expected_data.expected_aoi_id,
            expected_data.expected_subregion,
        )
        dataset_eval = evaluate_dataset_selection(
            agent_state,
            expected_data.expected_dataset_id,
            expected_data.expected_context_layer,
        )
        data_eval = evaluate_data_pull(
            agent_state,
            expected_start_date=expected_data.expected_start_date,
            expected_end_date=expected_data.expected_end_date,
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

    def _calculate_overall_score(self, evaluations: Dict[str, Any]) -> float:
        """Calculate overall score from individual evaluation scores."""
        scores = [
            evaluations["aoi_score"],
            evaluations["dataset_score"],
            evaluations["pull_data_score"],
            evaluations["answer_score"],
        ]
        return round(sum(scores) / len(scores), 2)
