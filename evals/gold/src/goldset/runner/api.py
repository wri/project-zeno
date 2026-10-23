"""Run one query against the GNW agent: stream ``POST /api/chat``, fetch the
final thread state (and the dashboard, if one was created) and score it with
every registered evaluator."""

import base64
import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import anyio
import httpx
from langchain_core._api import suppress_langchain_beta_warning
from langchain_core.load import loads

from goldset.eval_types import ExpectedData, TestResult
from goldset.runner.artifacts import build_artifact
from goldset.runner.base import BaseTestRunner

# A 5xx or a dropped connection on /api/chat is retried a couple of times.
# deploy-ephemeral.yaml warms up /api/chat itself before GOLD starts, but that
# is a best effort, not a guarantee the agent graph and its DB pool are warm
# for every request after it — this is the remaining safety net. merge_trials
# keeps an error from any one trial (see cli.py), so a single transient
# failure would otherwise mark the whole case ERROR even if its other trials
# pass cleanly.
TRANSIENT_CHAT_RETRIES = 2
TRANSIENT_CHAT_RETRY_DELAY_SECONDS = 5.0


def _is_transient_chat_error(error: BaseException) -> bool:
    """5xx and dropped-connection errors are worth retrying; nothing else is
    (a 4xx or a wall-clock timeout means retrying would not help)."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return isinstance(error, httpx.TransportError)


class APITestRunner(BaseTestRunner):
    """Test runner for API endpoint execution."""

    def __init__(
        self,
        api_base_url: str,
        api_token: str | None = None,
        ff: str | None = None,
        verbose: bool = False,
        wall_clock_limit: float = 900.0,
        analytics_token: str | None = None,
        analytics_environment: str | None = None,
    ):
        """Initialise with API configuration."""
        self.api_base_url = api_base_url
        self.api_token = api_token
        self.ff = ff
        self.verbose = verbose
        self.wall_clock_limit = wall_clock_limit
        # Set only for ground-truth runs: lets the runner re-read the agent's
        # own `source_url` to see the table it actually pulled.
        self.analytics_token = analytics_token
        self.analytics_environment = analytics_environment

    async def _fetch_pulled_data(
        self, client: httpx.AsyncClient, agent_state: dict[str, Any]
    ) -> dict[str, Any] | None:
        """The rows behind the agent's ``statistics.source_url``.

        ``statistics.data`` is empty on every observed pull — the table lives
        behind the URL, and nothing has ever fetched it, so every numeric check
        today reconstructs figures from ``charts_data`` instead. Reading it makes
        "the agent's pulled data" mean the data rather than the chart, so a
        correct pull that never reached a chart is no longer a failure.

        This result belongs to the agent, so it is read with the agent deployment's
        own analytics environment. Ground truth is fetched from back-end production

        Soft-fails to None like the dashboard fetch: this is enrichment, and
        killing a trial over a diagnostic GET would buy nothing.
        """
        from goldset.evaluators.utils import last_statistics
        from goldset.groundtruth.client import X_ENVIRONMENT, analytics_headers

        source_url = (last_statistics(agent_state) or {}).get("source_url")
        if not source_url:
            return None
        try:
            response = await client.get(
                str(source_url),
                headers=analytics_headers(
                    self.analytics_token or "",
                    self.analytics_environment or X_ENVIRONMENT,
                ),
            )
            response.raise_for_status()
            return (response.json().get("data") or {}).get("result") or None
        except Exception as error:
            print(f"Warning: failed to read pulled data from {source_url}: {error}")
            return None

    @staticmethod
    def _build_app_thread_url(api_base_url: str, thread_id: str) -> str | None:
        """Build GNW app thread URL from API base URL and session/thread ID.

        None for an ephemeral deployment, which is an API on a load balancer
        port with no app in front of it."""
        parsed = urlparse(api_base_url)
        if not parsed.scheme or not parsed.netloc:
            return f"{api_base_url.rstrip('/')}/app/threads/{thread_id}"

        host = parsed.hostname or ""
        if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
            return f"http://localhost:3000/app/threads/{thread_id}"
        if host.endswith(".elb.amazonaws.com"):
            return None

        app_host = host.removeprefix("api.") if host.startswith("api.") else host
        netloc = app_host
        if parsed.port:
            netloc = f"{app_host}:{parsed.port}"

        return urlunparse(
            (parsed.scheme, netloc, f"/app/threads/{thread_id}", "", "", ""),
        )

    async def run_test(
        self,
        query: str,
        expected_data: ExpectedData,
        artifact_sink: Callable[[dict[str, Any]], Any] | None = None,
        thread_id: str | None = None,
    ) -> TestResult:
        """Send one query to the agent and score the final state.

        Args:
            query: the user query to send.
            expected_data: the case's expectations, passed to every evaluator.
            artifact_sink: called once with the raw-state artefact (see
                runner/artifacts.py); a failure in it never fails the trial.
            thread_id: an existing thread to continue (a later turn of a
                multi-turn case); omit it to start a fresh thread.

        Returns:
            A TestResult with scores and diagnostics. Any exception, including
            the wall-clock timeout, returns an error TestResult instead of
            raising.
        """
        # A caller-supplied thread_id continues an existing conversation (a
        # multi-turn case); the default is a fresh single-turn thread.
        thread_id = thread_id or str(uuid4())
        trace_url = None
        app_thread_url = self._build_app_thread_url(self.api_base_url, thread_id)
        start_time = time.time()

        try:
            # The thread state is only final once the stream closes, so it is
            # read in full before fetching state (responses/trace_id are reset
            # per attempt in the retry loop below).
            payload = {
                "query": query,
                "user_persona": "Researcher",
                "thread_id": thread_id,
                "metadata": {"langfuse_tags": ["simple_e2e_test"]},
                "user_id": "test_user",
            }
            if self.ff:
                payload["ff"] = self.ff

            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"

            # Hard per-trial deadline: the 240s httpx timeout is per read, so a
            # stream that keeps sending keepalives never trips it. The wall
            # clock bounds the whole trial; TimeoutError becomes an error row
            # via the handler below.
            with anyio.fail_after(self.wall_clock_limit):
                async with httpx.AsyncClient(timeout=240.0) as client:
                    for attempt in range(TRANSIENT_CHAT_RETRIES + 1):
                        responses = []
                        trace_id = None
                        try:
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

                                        if stream_data.get("node") == "trace_info":
                                            update_data = json.loads(
                                                stream_data.get("update", "{}"),
                                            )
                                            trace_id = update_data.get("trace_id")
                                            trace_url = update_data.get("trace_url")
                            break
                        except (httpx.HTTPStatusError, httpx.TransportError) as error:
                            retries_left = TRANSIENT_CHAT_RETRIES - attempt
                            if not _is_transient_chat_error(error) or retries_left <= 0:
                                raise
                            print(
                                f"Warning: transient /api/chat error, "
                                f"{retries_left} retry(ies) left: {error}"
                            )
                            await anyio.sleep(TRANSIENT_CHAT_RETRY_DELAY_SECONDS)

                    state_response = await client.get(
                        f"{self.api_base_url}/api/threads/{thread_id}/state",
                        headers=headers,
                    )
                    state_response.raise_for_status()
                    response_data = state_response.json()
                    agent_state = response_data.get("state", {})
                    # LangChain's `loads` is marked beta and warns on every call;
                    # the warning is not actionable, so it is suppressed here.
                    with suppress_langchain_beta_warning():
                        agent_state = loads(agent_state, allowed_objects="core")

                    # Fetch dashboard details when a dashboard was created this turn.
                    # agent_state only carries the dashboard_id; AOI/widget details
                    # live on the dashboard resource itself. A failed fetch degrades
                    # to dashboard=None (soft failure) rather than erroring the row:
                    # the primary chat result already succeeded.
                    dashboard: dict[str, Any] | None = None
                    dashboard_id = (
                        agent_state.get("dashboard_id")
                        if isinstance(agent_state, dict)
                        else None
                    )
                    if dashboard_id:
                        try:
                            dashboard_response = await client.get(
                                f"{self.api_base_url}/api/dashboards/{dashboard_id}",
                                headers=headers,
                            )
                            dashboard_response.raise_for_status()
                            dashboard = dashboard_response.json()
                        except Exception as dashboard_error:
                            print(
                                f"Warning: failed to fetch dashboard {dashboard_id}: "
                                f"{dashboard_error}",
                            )
                            dashboard = None

                    # Carried on agent_state rather than as a fifth evaluator
                    # argument: it is the bag every evaluator already reads, and
                    # only the ground-truth check consumes it.
                    if expected_data.expected_ground_truth and self.analytics_token:
                        agent_state["pulled_data"] = await self._fetch_pulled_data(
                            client, agent_state
                        )

            api_duration_seconds = time.time() - start_time

            # Capture raw signals before scoring; capture must never fail a row.
            if artifact_sink is not None:
                try:
                    artifact_sink(
                        build_artifact(agent_state, dashboard, thread_id, trace_url)
                    )
                except Exception as artifact_error:
                    print(f"Warning: artifact capture failed: {artifact_error}")

            # Run evaluations off the loop thread: judge calls inside are
            # synchronous HTTP, and a slow one on the loop thread freezes
            # every other worker (and every timer, including the wall
            # clock above). abandon_on_cancel lets cancellation proceed;
            # the abandoned thread dies on the judge client's own timeout.
            evaluations = await anyio.to_thread.run_sync(
                self._run_evaluations,
                agent_state,
                expected_data,
                query,
                dashboard,
                abandon_on_cancel=True,
            )
            overall_score = self._calculate_overall_score(evaluations, expected_data)

            if self.verbose:
                print(
                    self._format_tool_trace(
                        query,
                        thread_id,
                        trace_id,
                        trace_url,
                        agent_state,
                        overall_score,
                    ),
                )

            kwargs = expected_data.to_dict()
            kwargs.update(evaluations)
            kwargs.pop("thread_id", None)
            kwargs.pop("trace_id", None)
            kwargs.pop("trace_url", None)
            kwargs.pop("query", None)
            kwargs.pop("overall_score", None)
            kwargs.pop("execution_time", None)

            return TestResult(
                thread_id=thread_id,
                app_thread_url=app_thread_url,
                trace_id=trace_id,
                trace_url=trace_url,
                query=query,
                overall_score=overall_score,
                execution_time=datetime.now().isoformat(),
                duration_seconds=api_duration_seconds,
                **kwargs,
            )

        except TimeoutError:
            message = (
                f"trial exceeded the {self.wall_clock_limit:.0f}s "
                "wall-clock limit (stream kept the connection alive)"
            )
            print(f"Error: {message}")
            return self._create_empty_evaluation_result(
                thread_id,
                trace_url or "",
                app_thread_url,
                query,
                expected_data,
                message,
                duration_seconds=time.time() - start_time,
            )
        except Exception as e:
            # str(e) can be empty (bare exceptions print as "Error: " and
            # land unreadable in the ledger), so always carry at least the
            # exception type.
            error_text = str(e) or type(e).__name__
            print(f"Error: {error_text}")
            return self._create_empty_evaluation_result(
                thread_id,
                trace_url or "",
                app_thread_url,
                query,
                expected_data,
                error_text,
                duration_seconds=time.time() - start_time,
            )

    @staticmethod
    def _indent(text: str, prefix: str) -> str:
        """Add prefix to each line of text."""
        return "\n".join(f"{prefix}{line}" for line in text.split("\n"))

    def _truncate(self, text: str, limit: int = 2000) -> str:
        """Truncate long text with an ellipsis indicator."""
        if len(text) <= limit:
            return text
        return text[:limit] + "\n... (truncated)"

    def _format_tool_trace(
        self,
        query: str,
        thread_id: str,
        trace_id: str | None,
        trace_url: str | None,
        agent_state: dict[str, Any],
        overall_score: float,
    ) -> str:
        """Format a human-readable tool trace for verbose output.

        Extracts tool calls from messages (tool_call/tool_message pairs)
        and decoded codeact_parts (code blocks and execution output),
        presenting them in a step-by-step chronological format.
        """
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append("TOOL TRACE")
        lines.append("=" * 70)
        lines.append(f"Query:     {query}")
        lines.append(f"Thread ID: {thread_id}")
        if trace_id:
            lines.append(f"Trace ID:  {trace_id}")
        if trace_url:
            lines.append(f"Trace URL: {trace_url}")
        lines.append(f"Score:     {overall_score}")

        messages = agent_state.get("messages", [])
        raw_parts = agent_state.get("codeact_parts", [])

        tool_calls: list[dict[str, Any]] = []
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        tool_calls.append(
                            {
                                "name": tc.get("name", "unknown"),
                                "args": tc.get("args", {}),
                                "id": tc.get("id", ""),
                            },
                        )

        for msg in messages:
            if hasattr(msg, "tool_call_id") and hasattr(msg, "content"):
                tid = msg.tool_call_id
                for tc in reversed(tool_calls):
                    if tc["id"] == tid and "output" not in tc:
                        tc["output"] = msg.content
                        break

        if tool_calls:
            lines.append("")
            lines.append("--- Tool Calls ---")
            for i, tc in enumerate(tool_calls, 1):
                lines.append("")
                lines.append(f"Tool {i}: {tc['name']}")
                if tc["args"]:
                    args_str = json.dumps(tc["args"], indent=2, default=str)
                    lines.append(f"  Input:\n{self._indent(args_str, '    ')}")
                if "output" in tc:
                    output = str(tc["output"])
                    output = self._truncate(output, 3000)
                    lines.append(f"  Output:\n{self._indent(output, '    ')}")

        if raw_parts:
            lines.append("")
            lines.append("--- Execution Trace ---")
            type_labels = {
                "code_block": "CODE",
                "text_output": "LLM",
                "execution_output": "OUTPUT",
            }
            step = 0
            for part in raw_parts:
                part_type = part.get("type", "unknown")
                try:
                    content = base64.b64decode(
                        part.get("content", ""),
                    ).decode("utf-8")
                except Exception:
                    content = part.get("content", "")
                label = type_labels.get(part_type, part_type.upper())
                step += 1
                content = self._truncate(content, 4000)
                lines.append("")
                lines.append(f"Step {step} [{label}]")
                lines.append(self._indent(content, "    "))

        if not tool_calls and not raw_parts:
            lines.append("")
            lines.append("(no tool trace available)")

        lines.append("=" * 70)
        return "\n".join(lines)
