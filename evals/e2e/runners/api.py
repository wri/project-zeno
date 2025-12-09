"""
API test runner for E2E testing framework.
"""

import json
from datetime import datetime
from uuid import uuid4

import httpx
from langchain_core.load import loads

from ..types import ExpectedData, TestResult
from .base import BaseTestRunner


class APITestRunner(BaseTestRunner):
    """Test runner for API endpoint execution."""

    def __init__(self, api_base_url: str, api_token: str = None):
        """Initialize with API configuration."""
        self.api_base_url = api_base_url
        self.api_token = api_token

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
        trace_url = None

        try:
            # Collect all streaming responses to ensure conversation completes
            responses = []
            trace_id = None

            # Prepare request payload
            payload = {
                "query": query,
                "user_persona": "Researcher",
                "thread_id": thread_id,
                "metadata": {"langfuse_tags": ["simple_e2e_test"]},
                "user_id": "test_user",
            }

            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"

            # Use httpx async client for streaming
            async with httpx.AsyncClient(timeout=240.0) as client:
                # Stream chat responses
                async with client.stream(
                    "POST",
                    f"{self.api_base_url}/api/chat",
                    json=payload,
                    headers=headers,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.strip():
                            stream_data = json.loads(line)
                            responses.append(stream_data)

                            # Capture trace ID from stream
                            if stream_data.get("node") == "trace_info":
                                update_data = json.loads(
                                    stream_data.get("update", "{}")
                                )
                                trace_id = update_data.get("trace_id")
                                trace_url = update_data.get("trace_url")

                # Get final agent state using the state endpoint
                state_response = await client.get(
                    f"{self.api_base_url}/api/threads/{thread_id}/state",
                    headers=headers,
                )
                state_response.raise_for_status()
                response_data = state_response.json()
                agent_state = response_data.get("state", {})
                agent_state = loads(agent_state)

            # Run evaluations
            evaluations = self._run_evaluations(
                agent_state, expected_data, query
            )
            overall_score = self._calculate_overall_score(
                evaluations, expected_data
            )

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
            print(f"Error: {e}")
            return self._create_empty_evaluation_result(
                thread_id, trace_url or "", query, expected_data, str(e), "api"
            )
