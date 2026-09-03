"""The Gemini code executor must report its usage to Langfuse.

This call goes straight to the ``google.genai`` SDK, so no LangChain callback
sees it. Before it was instrumented it was the single largest LLM call in an
insight turn and appeared in no trace at all — neither tokens nor cost — which
made every insight look cheaper than it was. These tests pin the reporting, and
pin that a telemetry failure can never break an analysis.
"""

import asyncio

import pytest

from src.agent.subagents.analyst.code_executors import gemini_executor as GE


class _Usage:
    prompt_token_count = 9_000
    candidates_token_count = 300
    thoughts_token_count = 0
    total_token_count = 9_300
    cached_content_token_count = 0


class _Response:
    usage_metadata = _Usage()


class _Recorder:
    """Captures what the executor reports, standing in for a Langfuse span."""

    def __init__(self):
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def spans(monkeypatch):
    """Replace generation_span with a recorder, and return the opened spans."""
    opened = []

    class _Span:
        def __init__(self, name, kwargs):
            self.name = name
            self.kwargs = kwargs
            self.recorder = _Recorder()

    def fake_span(name, **kwargs):
        span = _Span(name, kwargs)
        opened.append(span)

        class _CM:
            def __enter__(self_inner):
                return span.recorder

            def __exit__(self_inner, *exc):
                return False

        return _CM()

    monkeypatch.setattr(GE, "generation_span", fake_span)
    return opened


@pytest.fixture
def executor(monkeypatch):
    """A GeminiCodeExecutor with no real client and no real sleeps."""
    monkeypatch.setattr(GE.genai, "Client", lambda *a, **kw: object())
    monkeypatch.setattr(GE.asyncio, "sleep", _noop_sleep)
    ex = GE.GeminiCodeExecutor()
    ex.INITIAL_DELAY = 0
    return ex


async def _noop_sleep(*_args, **_kwargs):
    return None


def _run(coro):
    return asyncio.run(coro)


def test_successful_call_reports_usage_on_the_span(executor, spans):
    class _Models:
        def generate_content(self, **kwargs):
            return _Response()

    executor.client = type("C", (), {"models": _Models()})()

    result = _run(
        executor._call_model("gemini-3-flash-preview", [{"text": "x"}])
    )
    assert isinstance(result, _Response)

    assert len(spans) == 1
    assert spans[0].name == "analyst_code_executor"
    assert spans[0].kwargs["model"] == "gemini-3-flash-preview"
    # The usage the trace was missing entirely before instrumentation.
    assert spans[0].recorder.calls == [
        {"usage": {"input": 9_000, "output": 300, "total": 9_300}}
    ]


def test_exhausted_retries_mark_the_span_as_an_error(executor, spans):
    class _Models:
        def generate_content(self, **kwargs):
            raise RuntimeError("upstream 503")

    executor.client = type("C", (), {"models": _Models()})()

    with pytest.raises(RuntimeError, match="upstream 503"):
        _run(executor._call_model("gemini-3-flash-preview", [{"text": "x"}]))

    assert len(spans) == 1
    recorded = spans[0].recorder.calls
    assert recorded == [{"level": "ERROR", "status_message": "upstream 503"}]


def test_one_span_covers_the_whole_retry_loop(executor, spans):
    """Retries are transient failures of one logical call, so they belong in one
    span whose latency is the wall-clock time the caller actually waited."""
    attempts = {"n": 0}

    class _Models:
        def generate_content(self, **kwargs):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("flaky")
            return _Response()

    executor.client = type("C", (), {"models": _Models()})()

    _run(executor._call_model("gemini-3-flash-preview", [{"text": "x"}]))
    assert attempts["n"] == 3
    assert len(spans) == 1
    assert spans[0].recorder.calls == [
        {"usage": {"input": 9_000, "output": 300, "total": 9_300}}
    ]


def test_call_succeeds_with_langfuse_unconfigured(executor):
    """Uses the real generation_span, which is what production falls back to
    whenever Langfuse is unreachable or unconfigured (as it is here)."""

    class _Models:
        def generate_content(self, **kwargs):
            return _Response()

    executor.client = type("C", (), {"models": _Models()})()

    assert isinstance(
        _run(executor._call_model("m", [{"text": "x"}])), _Response
    )
