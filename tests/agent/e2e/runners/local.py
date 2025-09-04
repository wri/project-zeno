"""
Local test runner for E2E testing framework.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

import structlog
from langfuse import get_client
from langfuse.langchain import CallbackHandler

from ..types import ExpectedData, TestResult
from .base import BaseTestRunner


class LocalTestRunner(BaseTestRunner):
    """Test runner for local agent execution."""

    async def run_test(
        self,
        query: str,
        expected_data: ExpectedData,
        handler: Optional[CallbackHandler] = None,
    ) -> TestResult:
        """
        Run a single agent test using local agent instantiation.

        Args:
            query: User query to test
            expected_data: Expected test results for evaluation
            handler: Optional Langfuse callback handler

        Returns:
            TestResult with evaluation scores and metadata
        """
        from src.agents.agents import fetch_zeno

        # Setup agent
        agent = await fetch_zeno()

        # Create unique thread
        thread_id = uuid4().hex
        callbacks = [handler] if handler else [CallbackHandler()]
        langfuse = get_client()
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": callbacks,
            "metadata": {"langfuse_tags": ["simple_e2e_test"]},
        }

        trace_url = None
        try:
            # Set user_id in structlog context for tools (like the API does)
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(user_id="test_user")

            # Run agent
            _ = await agent.ainvoke(
                {"messages": [("user", query)], "user_persona": "Researcher"},
                config=config,
            )

            # Get trace URL using the thread_id as trace_id
            trace_id = trace_id = getattr(callbacks[0], "last_trace_id", None)
            trace_url = langfuse.get_trace_url(trace_id=trace_id)

            # Get final state
            state = await agent.aget_state(config=config)
            agent_state = state.values

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
                test_mode="local",
                **evaluations,
                **expected_data.to_dict(),
            )

        except Exception as e:
            return self._create_empty_evaluation_result(
                thread_id,
                trace_url or "",
                query,
                expected_data,
                str(e),
                "local",
            )
