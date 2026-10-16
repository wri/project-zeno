"""Emit Langfuse generation spans for LLM calls LangChain does not make.

The Langfuse LangChain callback traces every call that goes through a LangChain
runnable, and it propagates into tools on its own (async config propagation), so
tool-internal chains need nothing from this module. What it cannot see is a call
made with a provider SDK directly — currently the Gemini code executor in
``src.agent.subagents.analyst.code_executors``, which drives native code
execution that LangChain does not model.

Such a call is invisible in both tokens and cost, so a turn that runs it reads
cheaper than it was. ``generation_span`` puts it back on the trace. The v3
Langfuse SDK is OpenTelemetry-backed and so is the LangChain callback handler,
which is why a span opened here nests under the live trace without being handed
a parent: both read the same ambient OTEL context.

Everything here degrades to a no-op. Langfuse is unconfigured in CLI runs, tests
and local development, and telemetry must never be the reason an analysis fails.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Protocol

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Marks a trace that is NOT an agent turn: a one-off LLM call that has no turn
# trace to join (custom-area naming, or thread naming / language detection when
# no request span is active). A LangChain callback handler opens a trace per
# root invocation, so such a call gets a trace of its own.
#
# The ingest layer drops tagged traces that carry no AgentState from
# ``langfuse_traces``. That table is turn-level, and a tiny auxiliary trace
# would land as a zero-token EMPTY-outcome row and dilute every per-turn
# average. Their cost stays visible in Langfuse itself, and they share the
# thread's session id, so session-level cost remains complete. See
# ``src.api.services.langfuse.ingest._split_auxiliary``.
AUXILIARY_TAG = "auxiliary"


class UsageRecorder(Protocol):
    """What a caller may report once its LLM call returns."""

    def record(
        self,
        *,
        usage: Optional[Dict[str, int]] = None,
        model: Optional[str] = None,
        output: Optional[Any] = None,
        level: Optional[str] = None,
        status_message: Optional[str] = None,
    ) -> None: ...


class _NullRecorder:
    """Used when Langfuse is unconfigured or the span could not be opened."""

    def record(
        self,
        *,
        usage: Optional[Dict[str, int]] = None,
        model: Optional[str] = None,
        output: Optional[Any] = None,
        level: Optional[str] = None,
        status_message: Optional[str] = None,
    ) -> None:
        return None


class _SpanRecorder:
    def __init__(self, span: Any) -> None:
        self._span = span

    def record(
        self,
        *,
        usage: Optional[Dict[str, int]] = None,
        model: Optional[str] = None,
        output: Optional[Any] = None,
        level: Optional[str] = None,
        status_message: Optional[str] = None,
    ) -> None:
        try:
            fields: Dict[str, Any] = {}
            if usage:
                fields["usage_details"] = usage
            if model:
                fields["model"] = model
            if output is not None:
                fields["output"] = output
            if level:
                fields["level"] = level
            if status_message:
                fields["status_message"] = status_message
            if fields:
                self._span.update(**fields)
        except Exception:  # pragma: no cover - telemetry must not raise
            logger.debug("langfuse_generation_update_failed", exc_info=True)


@contextmanager
def generation_span(
    name: str,
    *,
    model: Optional[str] = None,
    input: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[UsageRecorder]:
    """Open a Langfuse generation span, yielding something to report usage to.

    Nests under whatever trace is currently active, so a call made inside an
    agent tool lands under that tool. Yields a no-op recorder when Langfuse is
    unavailable, so callers need no conditional of their own::

        with generation_span("analyst_code_executor", model=model) as gen:
            response = await call_the_sdk()
            gen.record(usage=usage_from(response))
    """
    try:
        from langfuse import get_client

        client = get_client()
    except Exception:
        logger.debug("langfuse_client_unavailable", exc_info=True)
        yield _NullRecorder()
        return

    try:
        cm = client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input,
            metadata=metadata,
        )
    except Exception:  # pragma: no cover - telemetry must not raise
        logger.debug("langfuse_generation_start_failed", exc_info=True)
        yield _NullRecorder()
        return

    with cm as span:
        yield _SpanRecorder(span)


def gemini_usage_details(response: Any) -> Optional[Dict[str, int]]:
    """Map a ``google.genai`` response's usage onto Langfuse's usage keys.

    Follows the convention the Langfuse LangChain handler uses for every other
    call, so one parser reads the whole table (see
    ``src.api.services.langfuse.parse._obs_usage``): ``input`` and ``output``
    are net of their breakdowns, which are reported as ``input_cache_read`` and
    ``output_reasoning``.

    * ``prompt_token_count`` includes cached tokens, so they are subtracted.
    * ``tool_use_prompt_token_count`` is not in ``prompt_token_count`` but is
      billed as input. For code execution it is the code and execution results
      the model reads back, so it is added to ``input``.
    * ``thoughts_token_count`` is not in ``candidates_token_count`` and is
      billed as output. Langfuse prices ``output_reasoning`` for Gemini models.
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None

    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    cached = _int(getattr(usage, "cached_content_token_count", None))
    prompt = _int(getattr(usage, "prompt_token_count", None))
    tool_use = _int(getattr(usage, "tool_use_prompt_token_count", None))
    output = _int(getattr(usage, "candidates_token_count", None))
    thoughts = _int(getattr(usage, "thoughts_token_count", None))
    total = _int(getattr(usage, "total_token_count", None))

    details = {
        "input": max(prompt - cached, 0) + tool_use,
        "output": output,
        "total": total or prompt + tool_use + output + thoughts,
    }
    if cached:
        details["input_cache_read"] = cached
    if thoughts:
        details["output_reasoning"] = thoughts
    return details


def auxiliary_config(
    run_name: str,
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    in_turn_request: bool = False,
) -> Dict[str, Any]:
    """A RunnableConfig that traces an LLM call made outside the agent graph.

    Without one of these, a call like thread naming or custom-area naming is
    billed and never appears anywhere: it runs outside the graph invocation,
    so there is no ambient handler for LangChain's config propagation to find.

    Set ``in_turn_request`` for a call made in the same request as an agent
    turn (thread naming, language detection in ``/api/chat``). When a request
    span is active, the handler joins that span's trace, which is the turn's
    trace. The call is then part of the turn's cost, and the trace must not
    get the auxiliary tag. Without an active span the call gets its own trace,
    which is tagged.

    Passing ``session_id`` (the thread id) is what lets a separate trace be
    joined back to the conversation it belongs to. Returns a config with no
    callbacks if Langfuse is unconfigured, so callers need no conditional.
    """
    config: Dict[str, Any] = {"run_name": run_name}
    metadata: Dict[str, Any] = {}
    if not (in_turn_request and _span_is_active()):
        metadata["langfuse_tags"] = [AUXILIARY_TAG]
    if session_id:
        metadata["langfuse_session_id"] = session_id
    if user_id:
        metadata["langfuse_user_id"] = user_id
    config["metadata"] = metadata

    try:
        from langfuse.langchain import CallbackHandler

        config["callbacks"] = [CallbackHandler()]
    except Exception:
        logger.debug("langfuse_callback_unavailable", exc_info=True)
    return config


def _span_is_active() -> bool:
    """True when an OpenTelemetry span is current, so a new observation joins
    its trace instead of opening one."""
    try:
        from opentelemetry import trace

        return trace.get_current_span().get_span_context().is_valid
    except Exception:  # pragma: no cover - telemetry must not raise
        return False
