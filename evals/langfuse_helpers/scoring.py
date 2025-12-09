"""
Langfuse scoring functionality for E2E testing framework.
"""

from langfuse import Langfuse

from evals.utils.eval_types import ExpectedData, TestResult


class LangfuseScorer:
    """Handles sending evaluation scores to Langfuse traces."""

    def __init__(self):
        """Initialize Langfuse client."""
        self.langfuse_client = Langfuse()

    def send_scores_to_trace(
        self, trace_id: str, result: TestResult, expected_data: ExpectedData
    ) -> None:
        """
        Send evaluation scores to Langfuse using trace ID.

        Args:
            trace_id: Langfuse trace ID
            result: Test result with scores
            expected_data: Expected test data for comments
        """
        if not trace_id:
            print("⚠️  No trace ID available, skipping Langfuse scoring")
            return

        try:
            # Add individual scores to the server-side trace
            self.langfuse_client.create_score(
                trace_id=trace_id,
                name="overall_score",
                value=result.overall_score,
                comment="Combined score across all evaluation criteria",
            )

            self.langfuse_client.create_score(
                trace_id=trace_id,
                name="aoi_selection_score",
                value=result.aoi_score,
                comment=f"Expected AOI: {expected_data.expected_aoi_id}, Actual: {result.actual_id or 'None'}",
            )

            self.langfuse_client.create_score(
                trace_id=trace_id,
                name="dataset_selection_score",
                value=result.dataset_score,
                comment=f"Expected Dataset: {expected_data.expected_dataset_id}, Actual: {result.actual_dataset_id or 'None'}",
            )

            self.langfuse_client.create_score(
                trace_id=trace_id,
                name="data_pull_score",
                value=result.pull_data_score,
                comment=f"Data pull success: {result.data_pull_success}, Rows: {result.row_count}",
            )

            self.langfuse_client.create_score(
                trace_id=trace_id,
                name="answer_quality_score",
                value=result.answer_score,
                comment="Answer evaluation based on expected criteria",
            )

            # Flush to ensure scores are sent
            self.langfuse_client.flush()

            print(f"✅ Evaluation scores sent to Langfuse trace: {trace_id}")

        except Exception as e:
            print(f"⚠️  Failed to send scores to Langfuse: {str(e)}")

    def add_scores_to_span(
        self, span, result: TestResult, expected_data: ExpectedData
    ) -> None:
        """
        Add evaluation scores to a Langfuse span (for local mode).

        Args:
            span: Langfuse span context
            result: Test result with scores
            expected_data: Expected test data for comments
        """
        try:
            span.score_trace(
                name="overall_score",
                value=result.overall_score,
                comment="Combined score across all evaluation criteria",
            )

            span.score_trace(
                name="aoi_selection_score",
                value=result.aoi_score,
                comment=f"Expected AOI: {expected_data.expected_aoi_id}, Actual: {result.actual_id or 'None'}",
            )

            span.score_trace(
                name="dataset_selection_score",
                value=result.dataset_score,
                comment=f"Expected Dataset: {expected_data.expected_dataset_id}, Actual: {result.actual_dataset_id or 'None'}",
            )

            span.score_trace(
                name="data_pull_score",
                value=result.pull_data_score,
                comment=f"Data pull success: {result.data_pull_success}, Rows: {result.row_count}",
            )

            span.score_trace(
                name="answer_quality_score",
                value=result.answer_score,
                comment="Answer evaluation based on expected criteria",
            )

        except Exception as e:
            print(f"⚠️  Failed to add scores to span: {str(e)}")
