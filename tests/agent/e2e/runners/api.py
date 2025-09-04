"""
API test runner for E2E testing framework.
"""

import json
from datetime import datetime
from uuid import uuid4

from langfuse import get_client

from client import ZenoClient

from ..types import ExpectedData, TestResult
from .base import BaseTestRunner


class APITestRunner(BaseTestRunner):
    """Test runner for API endpoint execution."""

    def __init__(self, client: ZenoClient):
        """Initialize with ZenoClient instance."""
        self.client = client

    async def run_test(
        self, query: str, expected_data: ExpectedData
    ) -> TestResult:
        """
        Run a single agent test using API endpoint.

        Args:
            query: User query to test
            expected_data: Expected test results for evaluation

        Returns:
            TestResult with evaluation scores and metadata
        """
        thread_id = uuid4().hex
        langfuse = get_client()
        trace_url = None

        try:
            # Collect all streaming responses to ensure conversation completes
            responses = []
            trace_id = None

            for stream in self.client.chat(
                query=query,
                user_persona="Researcher",
                thread_id=thread_id,
                metadata={"langfuse_tags": ["simple_e2e_test"]},
                user_id="test_user",
            ):
                responses.append(stream)
                # Capture trace ID from stream
                if stream.get("node") == "trace_info":
                    update_data = json.loads(stream.get("update", "{}"))
                    trace_id = update_data.get("trace_id")

            trace_url = langfuse.get_trace_url(trace_id=trace_id)
            # Get final agent state using the state endpoint
            state_response = self.client.get_thread_state(thread_id)
            agent_state = state_response["state"]

            # Run evaluations
            evaluations = self._run_evaluations(
                agent_state, expected_data, query
            )
            overall_score = self._calculate_overall_score(evaluations)

            return TestResult(
                thread_id=thread_id,
                trace_id=trace_id,
                trace_url=trace_url,
                query=query,
                overall_score=overall_score,
                execution_time=datetime.now().isoformat(),
                test_mode="api",
                **evaluations,
                **expected_data.to_dict(),
            )

        except Exception as e:
            return self._create_empty_evaluation_result(
                thread_id, trace_url or "", query, expected_data, str(e), "api"
            )
