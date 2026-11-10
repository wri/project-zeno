"""Shared runner logic: apply the evaluator registry to an agent state, and
build the error ``TestResult`` when a trial fails."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from goldset.eval_types import ExpectedData, TestResult
from goldset.registry import EVALUATORS


class BaseTestRunner(ABC):
    """Abstract base class for test runners."""

    @abstractmethod
    async def run_test(
        self,
        query: str,
        expected_data: ExpectedData,
    ) -> TestResult:
        """Send one query to the agent and return its scored TestResult.

        Args:
            query: User query to test
            expected_data: Expected test results for evaluation

        Returns:
            TestResult with evaluation scores and metadata

        """

    def _create_empty_evaluation_result(
        self,
        thread_id: str,
        trace_url: str,
        app_thread_url: str | None,
        query: str,
        expected_data: ExpectedData,
        error: str,
        duration_seconds: float | None = None,
    ) -> TestResult:
        """Create empty evaluation result for error cases."""
        kwargs = expected_data.to_dict()

        kwargs.pop("thread_id", None)
        kwargs.pop("trace_id", None)
        kwargs.pop("trace_url", None)
        kwargs.pop("query", None)
        kwargs.pop("overall_score", None)
        kwargs.pop("execution_time", None)

        return TestResult(
            thread_id=thread_id,
            app_thread_url=app_thread_url,
            trace_id=None,
            trace_url=trace_url,
            query=query,
            overall_score=0.0,
            execution_time=datetime.now().isoformat(),
            duration_seconds=duration_seconds,
            # AOI evaluation fields
            aoi_id_match_score=None,
            actual_id=None,
            actual_name=None,
            actual_subtype=None,
            actual_source=None,
            match_aoi_id=False,
            # Dataset evaluation fields
            dataset_id_match_score=None,
            dataset_parameter_match_score=None,
            context_layer_match_score=None,
            actual_dataset_id=None,
            actual_dataset_name=None,
            actual_dataset_parameters=None,
            actual_context_layer=None,
            # Data pull evaluation fields
            data_pull_exists_score=None,
            date_coverage_score=None,
            date_extraction_score=None,
            actual_extracted_start_date=None,
            actual_extracted_end_date=None,
            date_extraction_source=None,
            actual_extracted_windows=None,
            row_count=0,
            min_rows=1,
            data_pull_success=False,
            date_success=None,
            actual_start_date=None,
            actual_end_date=None,
            # Answer evaluation fields
            charts_answer_score=None,
            chart_answer_score_reason=None,
            agent_answer_score=None,
            agent_answer_score_reason=None,
            expected_text_match_score=None,
            expected_text_match_score_reason=None,
            actual_charts_answer=None,
            actual_charts_json=None,
            actual_agent_answer=None,
            # Clarification evaluation fields
            actual_clarification_requested=None,
            clarification_requested_score=None,
            # Suggested datasets evaluation fields
            suggested_datasets_match_score=None,
            actual_suggested_datasets=None,
            # Nudge evaluation fields
            nudge_match_score=None,
            actual_nudge_type=None,
            actual_nudge_options=None,
            # Dashboard evaluation fields
            dashboard_created_score=None,
            actual_dashboard_created=None,
            actual_dashboard_id=None,
            dashboard_aoi_match_score=None,
            actual_dashboard_aoi_count=None,
            actual_dashboard_aoi_id=None,
            actual_dashboard_aoi_source=None,
            dashboard_widgets_match_score=None,
            actual_dashboard_widget_types=None,
            dashboard_widgets_valid_score=None,
            # Expected data
            **kwargs,
            # Error
            error=error,
        )

    def _run_evaluations(
        self,
        agent_state: dict[str, Any],
        expected_data: ExpectedData,
        query: str = "",
        dashboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run every registered evaluator on the agent state.

        Iterates the registry in its declared order and merges the result
        dicts, so a later evaluator wins a key collision. Judge errors from
        every evaluator are collected into ``judge_errors``.
        """
        evaluations: dict[str, Any] = {}
        judge_errors: list[str] = []
        for spec in EVALUATORS:
            result = spec.run(agent_state, expected_data, query, dashboard)
            judge_errors.extend(result.pop("judge_errors", []) or [])
            evaluations.update(result)
        evaluations["judge_errors"] = judge_errors
        return evaluations

    def _calculate_overall_score(
        self,
        evaluations: dict[str, Any],
        expected_data: ExpectedData,
    ) -> float:
        """Mean of the applicable original checks, rounded to two decimal places.

        Display only: it appears in --verbose output, is never written to the
        ledger (``NON_CHECK_SCORES`` excludes it) and never decides a verdict,
        which comes from ``buckets.row_verdict``. Checks added after the
        original set are deliberately left out, so the number stays comparable
        with older output. Only checks the case has an expectation for are
        averaged, and a None score is skipped.
        """
        scores = []

        if expected_data.expected_clarification is not None:
            scores.append(evaluations.get("clarification_requested_score"))

        if expected_data.expected_aoi_ids:
            scores.append(evaluations.get("aoi_id_match_score"))

        if expected_data.expected_dataset_id:
            scores.append(evaluations.get("dataset_id_match_score"))
        if expected_data.expected_dataset_parameters:
            scores.append(evaluations.get("dataset_parameter_match_score"))
        if expected_data.expected_context_layer:
            scores.append(evaluations.get("context_layer_match_score"))

        # Data pull: only when the case expects an insight or answer.
        if expected_data.expects_data_pull():
            scores.append(evaluations.get("data_pull_exists_score"))
        # Date: only `date_extraction_score` counts. `date_coverage_score` is
        # reported for diagnosis but excluded, because agent_state's recorded range
        # is inconsistent (see data_pull_evaluator's module docstring).
        if expected_data.expected_start_date and expected_data.expected_end_date:
            scores.append(evaluations.get("date_extraction_score"))

        if expected_data.expected_suggested_datasets:
            scores.append(evaluations.get("suggested_datasets_match_score"))

        if expected_data.expected_nudge_type or expected_data.expected_nudge_options:
            scores.append(evaluations.get("nudge_match_score"))

        # NOTE: uses `is not None` (not truthy) so expected_dashboard_created=False
        # guardrail rows are still included; a truthy check would silently drop them.
        if expected_data.expected_dashboard_created is not None:
            scores.append(evaluations.get("dashboard_created_score"))
        if expected_data.expected_dashboard_created and expected_data.expected_aoi_ids:
            scores.append(evaluations.get("dashboard_aoi_match_score"))
        if expected_data.expected_dashboard_widgets:
            scores.append(evaluations.get("dashboard_widgets_match_score"))
        if expected_data.expected_dashboard_created:
            scores.append(evaluations.get("dashboard_widgets_valid_score"))

        if expected_data.expected_answer:
            scores.append(evaluations.get("charts_answer_score"))
            scores.append(evaluations.get("agent_answer_score"))
        if expected_data.expected_text:
            scores.append(evaluations.get("expected_text_match_score"))

        valid_scores = [s for s in scores if s is not None]

        if not valid_scores:
            return 0.0

        return round(sum(valid_scores) / len(valid_scores), 2)
