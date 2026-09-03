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

# Marks a trace that is NOT an agent turn: a one-off LLM call made by its own
# HTTP request (thread naming, area naming) or before the graph is invoked
# (language detection). Such a call creates its own root trace, because a
# LangChain callback handler opens a trace per root invocation and there is no
# turn to nest it under.
#
# The ingest layer drops these from ``langfuse_traces`` — that table is
# turn-level, and a tiny auxiliary trace carries no AgentState, so it would land
# as a zero-token EMPTY-outcome row and dilute every per-turn average. Their
# cost stays visible in Langfuse itself, and they share the thread's session id,
# so session-level cost remains complete. See
# ``src.api.services.langfuse.ingest.ingest_window``.
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

    Langfuse keys prompt tokens as ``input`` *excluding* the cached ones, which
    it wants separately as ``input_cache_read`` — the same split the parser
    relies on (see ``src.api.services.langfuse.parse._obs_usage``). Gemini's
    ``prompt_token_count`` includes the cached ones, so they are subtracted out
    here. Thinking tokens are billed as output, so they are folded into it.
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
    output = _int(getattr(usage, "candidates_token_count", None)) + _int(
        getattr(usage, "thoughts_token_count", None)
    )
    total = _int(getattr(usage, "total_token_count", None))

    details = {
        "input": max(prompt - cached, 0),
        "output": output,
        "total": total or prompt + output,
    }
    if cached:
        details["input_cache_read"] = cached
    return details


def auxiliary_config(
    run_name: str,
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A RunnableConfig that traces an LLM call made outside an agent turn.

    Without one of these, a call like thread naming or custom-area naming is
    billed and never appears anywhere: it runs in its own request, so there is
    no ambient handler for LangChain's config propagation to find.

    Passing ``session_id`` (the thread id) is what lets the resulting trace be
    joined back to the conversation it belongs to. Returns a config with no
    callbacks if Langfuse is unconfigured, so callers need no conditional.
    """
    config: Dict[str, Any] = {"run_name": run_name}
    metadata: Dict[str, Any] = {"langfuse_tags": [AUXILIARY_TAG]}
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
