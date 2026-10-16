"""Unit tests for src/shared/langfuse_tracing.py.

The point of this module is that telemetry never breaks an analysis, so most of
these assert the no-op paths hold when Langfuse is unconfigured (as it is in
tests) and that the Gemini usage mapping matches the keys the parser reads back
out of Langfuse.
"""

from contextlib import contextmanager

import pytest

from src.shared.langfuse_tracing import (
    AUXILIARY_TAG,
    auxiliary_config,
    gemini_usage_details,
    generation_span,
)


class _FakeSpan:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class _FakeClient:
    def __init__(self):
        self.opened = []

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        span = _FakeSpan()
        self.opened.append((kwargs, span))
        yield span


@pytest.fixture(autouse=True)
def fake_langfuse(monkeypatch):
    """Keep the suite hermetic: with ``LANGFUSE_*`` in the environment (as with
    the repo ``.env``) the real client would export spans to that host."""
    import langfuse
    import langfuse.langchain

    client = _FakeClient()
    monkeypatch.setattr(langfuse, "get_client", lambda: client)
    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", object)
    return client


class _Usage:
    prompt_token_count = 12_000
    candidates_token_count = 400
    thoughts_token_count = 150
    total_token_count = 12_550
    cached_content_token_count = 8_000


class _Response:
    usage_metadata = _Usage()


# --------------------------------------------------------------------------- #
# usage mapping
# --------------------------------------------------------------------------- #
def test_cached_tokens_are_reported_separately_from_input():
    """Langfuse wants `input` net of cache and `input_cache_read` beside it —
    the same split src/api/services/langfuse/parse.py reads back."""
    details = gemini_usage_details(_Response())
    assert details["input"] == 4_000  # 12_000 prompt - 8_000 cached
    assert details["input_cache_read"] == 8_000
    # The two must reconstruct Gemini's own prompt count, or the parser's
    # input + input_cache_read sum is wrong.
    assert details["input"] + details["input_cache_read"] == 12_000


def test_thinking_tokens_are_reported_as_output_reasoning():
    """Same convention as the LangChain handler: ``output`` net of thoughts,
    with the thoughts beside it under the key Langfuse prices for Gemini."""
    details = gemini_usage_details(_Response())
    assert details["output"] == 400
    assert details["output_reasoning"] == 150


def test_tool_use_prompt_tokens_are_billed_as_input():
    """For code execution, the code and results the model reads back are in
    ``tool_use_prompt_token_count``, outside ``prompt_token_count``."""

    class U:
        prompt_token_count = 1_000
        tool_use_prompt_token_count = 900
        candidates_token_count = 50
        thoughts_token_count = 20
        total_token_count = 1_970

    class R:
        usage_metadata = U()

    details = gemini_usage_details(R())
    assert details == {
        "input": 1_900,
        "output": 50,
        "output_reasoning": 20,
        "total": 1_970,
    }
    # The parser's per-side sums must reconstruct Gemini's own total.
    assert sum(v for k, v in details.items() if k != "total") == 1_970


def test_total_is_taken_from_the_response():
    assert gemini_usage_details(_Response())["total"] == 12_550


def test_missing_cache_key_is_omitted_rather_than_zero():
    class U:
        prompt_token_count = 10
        candidates_token_count = 2
        total_token_count = 12

    class R:
        usage_metadata = U()

    details = gemini_usage_details(R())
    assert "input_cache_read" not in details
    assert details == {"input": 10, "output": 2, "total": 12}


def test_response_without_usage_yields_none():
    assert gemini_usage_details(object()) is None


def test_garbage_usage_values_do_not_raise():
    class U:
        prompt_token_count = "not a number"
        candidates_token_count = None
        total_token_count = None

    class R:
        usage_metadata = U()

    assert gemini_usage_details(R()) == {"input": 0, "output": 0, "total": 0}


# --------------------------------------------------------------------------- #
# span reporting
# --------------------------------------------------------------------------- #
def test_generation_span_reports_to_the_langfuse_span(fake_langfuse):
    with generation_span("probe", model="m") as gen:
        gen.record(usage={"input": 1, "output": 2, "total": 3})
        gen.record(level="ERROR", status_message="boom")

    [(kwargs, span)] = fake_langfuse.opened
    assert kwargs["as_type"] == "generation"
    assert kwargs["name"] == "probe"
    assert kwargs["model"] == "m"
    assert span.updates == [
        {"usage_details": {"input": 1, "output": 2, "total": 3}},
        {"level": "ERROR", "status_message": "boom"},
    ]


# --------------------------------------------------------------------------- #
# no-op behaviour (Langfuse unconfigured or broken)
# --------------------------------------------------------------------------- #


def test_generation_span_yields_a_recorder_even_on_failure():
    """A caller must never have to guard the record() call."""
    with generation_span("probe") as gen:
        assert hasattr(gen, "record")


def test_auxiliary_config_tags_and_names_the_call():
    config = auxiliary_config("generate_thread_name", session_id="t1")
    assert config["run_name"] == "generate_thread_name"
    assert config["metadata"]["langfuse_tags"] == [AUXILIARY_TAG]
    # The session id is what joins the auxiliary trace back to its thread.
    assert config["metadata"]["langfuse_session_id"] == "t1"


def test_in_turn_call_joins_an_active_request_span_untagged():
    """Inside an active request span the handler joins the turn's trace, and
    the auxiliary tag would land on the turn. So it is left off."""
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("POST /api/chat"):
        joined = auxiliary_config("detect_language", in_turn_request=True)
        separate = auxiliary_config("name_custom_area")
    assert "langfuse_tags" not in joined["metadata"]
    assert separate["metadata"]["langfuse_tags"] == [AUXILIARY_TAG]


def test_in_turn_call_without_a_request_span_gets_its_own_tagged_trace():
    config = auxiliary_config("detect_language", in_turn_request=True)
    assert config["metadata"]["langfuse_tags"] == [AUXILIARY_TAG]


def test_auxiliary_config_omits_ids_it_was_not_given():
    metadata = auxiliary_config("name_custom_area")["metadata"]
    assert "langfuse_session_id" not in metadata
    assert "langfuse_user_id" not in metadata


def test_a_client_that_raises_still_yields_a_working_recorder(monkeypatch):
    """The failure the module's try/except exists to absorb: Langfuse present
    but broken. Callers must still be able to open a span and report to it."""
    import sys

    class _Exploding:
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("langfuse is down")

    monkeypatch.setitem(
        sys.modules,
        "langfuse",
        type("M", (), {"get_client": staticmethod(lambda: _Exploding())}),
    )
    with generation_span("probe", model="m") as gen:
        gen.record(usage={"input": 1, "output": 1, "total": 2})


def test_an_unimportable_client_still_yields_a_recorder(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "langfuse", None)
    with generation_span("probe") as gen:
        gen.record(usage={"input": 1, "output": 1, "total": 2})
