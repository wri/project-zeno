"""Parse Langfuse traces into structured rows.

A Langfuse trace corresponds to one agent *turn*. Its ``output`` is the full
final ``AgentState`` snapshot (src/agent/state.py) — carrying ``aoi_selection``,
``dataset``, ``statistics``, ``insight_id`` etc. alongside ``messages`` — so the
structured domain fields are read directly from that contract (no regex).

Three important correctness points, validated against real production traces:

* ``output`` (and ``output.messages``) is **thread-cumulative** (state uses
  ``operator.add``). So per-turn metrics (tokens, tool calls) are computed over
  the **active-turn window** of the message stream, NOT the whole history —
  otherwise late turns get inflated counts.
* A single tool result with ``status="error"`` is common (~30% of turns) and the
  agent usually recovers, so it must NOT by itself mark the turn a failure. We
  record ``tool_error_count`` as a separate signal and classify the outcome from
  the final active-turn AI message.
* The message stream only carries the usage of the calls the **agent itself**
  made: a tool that calls an LLM of its own returns a ToolMessage, never an
  AIMessage, so its tokens are absent from ``output.messages`` entirely. Token
  columns therefore come from the trace's **generation observations** when they
  are supplied, and fall back to the message stream when they are not
  (``derived.usage_source`` records which). On one measured production trace the
  message stream accounted for 35,466 of 44,491 tokens and 67% of the cost —
  the missing third was ``pick_aoi``, ``pick_dataset`` and the insight
  text generator, which Langfuse had traced correctly all along.

These functions are pure (no IO). ``parse_trace`` returns derived column values
plus a ``derived`` JSONB bundle; ``ingest`` adds identity/raw fields.
"""

from __future__ import annotations

import json
from typing import Any, Optional

# Bump on any change to derivation logic; to apply it to existing rows, re-run
# ingestion for the affected window (`ingest-langfuse-traces --backfill --since`).
# v3: token columns are sourced from generation observations (all LLM calls in
# the turn) instead of the AIMessage stream (the agent's own calls only), and
# ``total_cost`` falls back to the observation sum when ``trace.totalCost`` is
# null. ``turn_tokens`` steps UP for any turn whose tools call an LLM; the
# agent-only figure it used to hold is kept as ``agent_tokens``.
PARSER_VERSION = 3

# Top-level keys we expect on ``trace.output`` (the AgentState snapshot).
# Used for drift detection: unknown keys => additive drift (benign, logged);
# a sharp drop in a known key's fill-rate => subtractive drift (investigate).
EXPECTED_STATE_KEYS = frozenset(
    {
        "messages",
        "user_persona",
        "language",
        "view_context",
        "aoi_selection",
        "dataset",
        "nudge",
        "start_date",
        "end_date",
        "statistics",
        "imagery",
        "cited_articles",
        "dashboard_id",
        "insight",
        "insight_id",
        "follow_up_suggestions",
        "charts_data",
        "codeact_parts",
    }
)

# Display name(s) the agent uses for a global (all-countries) selection. Defined
# here to keep this module dependency-free; a contract test asserts it still
# matches GLOBAL_AOI_SELECTION_NAME in src/agent/.../global_queries.py so a
# rename there fails CI loudly rather than silently flipping is_global.
GLOBAL_AOI_NAMES = frozenset(
    {"All countries in the world", "Selected all countries in the world"}
)

_REFUSAL_NEEDLES = (
    "i can't",
    "i cannot",
    "i'm sorry",
    "i am sorry",
    "i'm unable",
    "i am unable",
    "unable to",
    "apologi",  # apologize / apologies
)

# Optional language detection (low-value, isolated). Works without the dep.
try:  # pragma: no cover - exercised only when langid is installed
    import langid as _langid
except Exception:  # pragma: no cover
    _langid = None


# --------------------------------------------------------------------------- #
# Message helpers
# --------------------------------------------------------------------------- #
def _mtype(m: dict[str, Any]) -> str:
    t = (m.get("type") or m.get("role") or "").lower()
    return {"assistant": "ai", "user": "human"}.get(t, t)


def _text(content: Any) -> str:
    """Flatten message content (string or list of content blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for c in content:
            if isinstance(c, str):
                out.append(c)
            elif isinstance(c, dict):
                v = c.get("text") or c.get("content")
                if isinstance(v, str):
                    out.append(v)
        return "\n".join(o for o in out if o)
    if isinstance(content, dict):
        v = content.get("text") or content.get("content")
        return v if isinstance(v, str) else ""
    return ""


def _finish_reason(m: dict[str, Any]) -> str:
    meta = m.get("response_metadata") or {}
    fr = (
        meta.get("finish_reason")
        or meta.get("stop_reason")
        or m.get("finish_reason")
        or m.get("stop_reason")
        or ""
    )
    return str(fr).lower()


def _is_meaningful_human(text: str) -> bool:
    """Skip synthetic UI-action human messages ('User selected ...')."""
    if not text or not text.strip():
        return False
    t = text.strip().lower()
    synthetic_prefixes = (
        "user selected",
        "user clicked",
        "user chose",
        "user set",
        "user changed",
        "user uploaded",
        "user drew",
        "user toggled",
        "selected aoi",
        "selected dataset",
    )
    if t.startswith(synthetic_prefixes):
        return False
    return any(ch.isalnum() for ch in text)


def _usage(m: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return (input, output, total, cache_read) tokens for an AI message,
    tolerant of Gemini/LangChain and OpenAI key shapes."""
    u = m.get("usage_metadata") or m.get("usage") or {}
    if not isinstance(u, dict):
        return 0, 0, 0, 0
    inp = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
    out = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
    total = int(u.get("total_tokens") or (inp + out))
    details = u.get("input_token_details") or {}
    cache = int(
        details.get("cache_read")
        or details.get("cache_read_input_tokens")
        or 0
    )
    return inp, out, total, cache


def _looks_like_refusal(text: str) -> bool:
    t = (text or "").strip().lower()
    return bool(t) and any(n in t for n in _REFUSAL_NEEDLES)


# --------------------------------------------------------------------------- #
# Active-turn windowing
# --------------------------------------------------------------------------- #
def _last_meaningful_human(
    msgs: list[dict[str, Any]], lo: int, hi: int
) -> Optional[int]:
    for j in range(hi, lo - 1, -1):
        m = msgs[j]
        if _mtype(m) == "human" and _is_meaningful_human(
            _text(m.get("content"))
        ):
            return j
    return None


def active_turn_window(
    msgs: list[dict[str, Any]],
) -> tuple[Optional[int], Optional[int]]:
    """Inclusive (start, end) indices of the latest turn within ``msgs``.

    A turn ends at an AI message that finished (``end_turn``, or ``stop``
    followed by a human / end of list) and starts at the latest meaningful human
    message before it. Returns (None, None) for empty input.
    """
    if not msgs:
        return None, None

    end_idxs: list[int] = []
    for i, m in enumerate(msgs):
        if _mtype(m) != "ai":
            continue
        fr = _finish_reason(m)
        if fr == "end_turn":
            end_idxs.append(i)
        elif fr == "stop":
            nxt = i + 1
            if nxt >= len(msgs) or _mtype(msgs[nxt]) == "human":
                end_idxs.append(i)

    if not end_idxs:
        start = _last_meaningful_human(msgs, 0, len(msgs) - 1)
        return start, len(msgs) - 1

    end = end_idxs[-1]
    prev_end = end_idxs[-2] if len(end_idxs) > 1 else -1
    start = _last_meaningful_human(msgs, prev_end + 1, end - 1)
    if start is None:
        start = prev_end + 1 if prev_end + 1 <= end else end
    return start, end


# --------------------------------------------------------------------------- #
# State parsing (the AgentState contract)
# --------------------------------------------------------------------------- #
def parse_state(output: Any) -> dict[str, Any]:
    """Derive domain fields from ``trace.output`` (the AgentState snapshot).

    Current-state fields (aoi/dataset/insight) are per-turn-meaningful (the
    selection in effect this turn). Cumulative fields (datasets/statistics ids)
    reflect the whole thread and are named/kept accordingly.
    """
    out = output if isinstance(output, dict) else {}
    unknown = sorted(set(out) - EXPECTED_STATE_KEYS)
    # None => not applicable (output absent, ~6% of traces — not a contract
    # violation). True/False only when output IS a dict, so the drift metric
    # (unrecognized_contract_rate) flags genuinely malformed AgentState shapes.
    recognized = ("messages" in out) if isinstance(output, dict) else None

    aoi_sel = out.get("aoi_selection") or {}
    aois = aoi_sel.get("aois") or []
    aois = [a for a in aois if isinstance(a, dict)]
    primary_aoi = aois[0] if aois else {}
    aoi_name = aoi_sel.get("name") or primary_aoi.get("name")
    is_global = (
        bool(aoi_sel.get("name") in GLOBAL_AOI_NAMES) if aoi_sel else False
    )

    dataset = out.get("dataset") or {}
    if not isinstance(dataset, dict):
        dataset = {}

    stats = [s for s in (out.get("statistics") or []) if isinstance(s, dict)]
    datasets_cumulative = list(
        dict.fromkeys(
            s.get("dataset_name") for s in stats if s.get("dataset_name")
        )
    )
    statistics_ids = [s.get("id") for s in stats if s.get("id")]

    primary_dataset_name = dataset.get("dataset_name") or (
        datasets_cumulative[-1] if datasets_cumulative else None
    )

    insight_id = out.get("insight_id") or None
    has_insight = bool(insight_id) or bool(out.get("insight"))

    return {
        # current-state columns
        "aoi_name": aoi_name or None,
        "aoi_type": primary_aoi.get("subtype") or None,
        "primary_dataset_name": primary_dataset_name or None,
        "has_insight": has_insight,
        "is_global": is_global,
        "insight_id": insight_id,
        # long-tail / cumulative (-> derived JSONB)
        "aoi_source": primary_aoi.get("source") or None,
        "aoi_count": len(aois),
        "aois": [
            {
                "name": a.get("name"),
                "type": a.get("subtype"),
                "source": a.get("source"),
            }
            for a in aois
        ],
        "primary_dataset_id": dataset.get("dataset_id"),
        "analysis_start_date": out.get("start_date") or None,
        "analysis_end_date": out.get("end_date") or None,
        "datasets_analysed_cumulative": datasets_cumulative,
        "statistics_ids": statistics_ids,
        # drift signals
        "unknown_output_keys": unknown,
        "recognized_contract": recognized,
    }


# --------------------------------------------------------------------------- #
# Message parsing (active-turn metrics + outcome primitives)
# --------------------------------------------------------------------------- #
_DATASET_ARG_KEYS = ("dataset_name", "dataset", "dataset_id")


def parse_messages(
    output_messages: Any, input_messages: Any
) -> dict[str, Any]:
    """Derive prompt/answer, outcome primitives and per-turn metrics from the
    active-turn window of ``output.messages``."""
    msgs = [m for m in (output_messages or []) if isinstance(m, dict)]
    in_msgs = [m for m in (input_messages or []) if isinstance(m, dict)]

    start, end = active_turn_window(msgs)
    window = (
        msgs[start : end + 1] if start is not None and end is not None else []
    )

    # prompt: active-turn human, else first meaningful human in input/output
    prompt = ""
    if window and _mtype(window[0]) == "human":
        prompt = _text(window[0].get("content")).strip()
    if not prompt:
        for m in in_msgs + msgs:
            if _mtype(m) == "human" and _is_meaningful_human(
                _text(m.get("content"))
            ):
                prompt = _text(m.get("content")).strip()
                break

    # final AI message of the window -> answer + finish_reason
    answer = ""
    answer_finish_reason = None
    had_ai_message = False
    for m in reversed(window):
        if _mtype(m) == "ai":
            had_ai_message = True
            answer = _text(m.get("content")).strip()
            answer_finish_reason = _finish_reason(m) or None
            if answer:
                break

    # per-turn metrics over the window
    t_in = t_out = t_total = t_cache = 0
    tool_calls = 0
    tool_error_count = 0
    tools_used: list[str] = []
    turn_datasets: list[str] = []
    had_tool_call = False
    for m in window:
        mt = _mtype(m)
        if mt == "ai":
            i, o, tot, c = _usage(m)
            t_in += i
            t_out += o
            t_total += tot
            t_cache += c
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                had_tool_call = True
                tool_calls += 1
                name = tc.get("name")
                if name and name not in tools_used:
                    tools_used.append(name)
                args = tc.get("args") or {}
                if isinstance(args, dict):
                    for k in _DATASET_ARG_KEYS:
                        v = args.get(k)
                        if (
                            isinstance(v, str)
                            and v.strip()
                            and v not in turn_datasets
                        ):
                            turn_datasets.append(v.strip())
        elif mt == "tool":
            had_tool_call = True
            if str(m.get("status") or "").lower() == "error":
                tool_error_count += 1

    has_answer = bool(answer)
    answer_is_refusal = _looks_like_refusal(answer)
    outcome = derive_outcome(
        has_answer=has_answer,
        had_ai_message=had_ai_message,
        answer_is_refusal=answer_is_refusal,
        had_tool_call=had_tool_call,
    )
    language, language_confidence = _detect_language(prompt)

    return {
        "prompt": prompt or None,
        "answer": answer or None,
        # outcome primitives + derived label
        "has_answer": has_answer,
        "answer_finish_reason": answer_finish_reason,
        "answer_is_refusal": answer_is_refusal,
        "had_tool_call": had_tool_call,
        "tool_error_count": tool_error_count,
        "outcome": outcome,
        # per-turn metrics
        "turn_input_tokens": t_in,
        "turn_output_tokens": t_out,
        "turn_tokens": t_total,
        "turn_tool_calls": tool_calls,
        # long-tail (-> derived JSONB)
        "cache_read_tokens": t_cache,
        "turn_tools_used": tools_used,
        "turn_datasets": turn_datasets,
        "had_ai_message": had_ai_message,
        "language": language,
        "language_confidence": language_confidence,
    }


def derive_outcome(
    *,
    has_answer: bool,
    had_ai_message: bool,
    answer_is_refusal: bool,
    had_tool_call: bool,
) -> str:
    """Turn-level outcome from primitives (re-derivable; not an opaque enum)."""
    if not has_answer:
        return "ERROR" if had_ai_message else "EMPTY"
    if answer_is_refusal:
        return "SOFT_ERROR"
    if not had_tool_call:
        return "DEFER"
    return "ANSWER"


def _detect_language(
    text: Optional[str],
) -> tuple[Optional[str], Optional[float]]:
    if not _langid or not text or len(text.strip()) < 12:
        return None, None
    try:  # pragma: no cover - depends on optional dep
        lang, score = _langid.classify(text)
        return str(lang), float(score)
    except Exception:  # pragma: no cover
        return None, None


# The number of JSON-decode passes ``_as_state_dict`` will try. The LangChain
# callback serialises the graph output to a JSON string before handing it to
# Langfuse, and an export of the same trace can add a second layer, so two is
# the observed maximum; the cap just stops a pathological value from looping.
_MAX_JSON_DECODE_PASSES = 4


def _as_state_dict(output: Any) -> Any:
    """Return ``trace.output`` as a dict when it is one, decoding JSON strings.

    A trace whose ``output`` arrives as a JSON *string* rather than an object
    used to zero every metric on the row, silently: the message walk needs a
    dict, and ``parse_state`` classifies a non-dict output as "not applicable"
    rather than as a contract violation, so the drift monitor stayed quiet too.
    Decoding here means the shape of the transport cannot cost us the data.

    Anything that does not decode to a dict is returned unchanged, so the
    existing "output absent" handling still applies.
    """
    value = output
    for _ in range(_MAX_JSON_DECODE_PASSES):
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return output
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return output
    return value if isinstance(value, dict) else output


# --------------------------------------------------------------------------- #
# Observations (the usage source)
# --------------------------------------------------------------------------- #
# The LangGraph model node. A generation whose nearest named ancestor is this
# chain is a call the agent made itself; anything under a TOOL observation was
# made by that tool.
_AGENT_NODE_NAME = "model"
AGENT_COMPONENT = "agent"
OTHER_COMPONENT = "other"


def _obs_usage(obs: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return (input, output, total, cache_read) tokens for one observation.

    Langfuse splits cached prompt tokens out of ``input`` and reports them as
    ``input_cache_read``, whereas LangChain's ``usage_metadata.input_tokens``
    includes them. We add them back so the token columns keep the same meaning
    they had when they were derived from the message stream — otherwise the
    series silently drops by the cache-hit rate (~45% on measured traces).
    """
    u = obs.get("usageDetails") or {}
    cache = _int(u.get("input_cache_read"))
    inp = _int(u.get("input")) + cache
    out = _int(u.get("output"))
    total = _int(u.get("total")) or (inp + out)
    return inp, out, total, cache


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _obs_cost(obs: dict[str, Any]) -> float:
    """Cost of one observation, preferring Langfuse's own total."""
    total = obs.get("totalCost")
    if total is not None:
        try:
            return float(total)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(obs.get("inputCost") or 0) + float(
            obs.get("outputCost") or 0
        )
    except (TypeError, ValueError):
        return 0.0


def _component(obs: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    """Who made this call: ``agent``, the owning tool's name, or ``other``.

    Walks up ``parentObservationId`` to the nearest TOOL observation (the tool
    that owns the call) or to the LangGraph ``model`` node (the agent's own
    call). Anything else — a generation outside both, e.g. one emitted by a
    manually instrumented span — lands in ``other`` rather than inflating the
    agent's share.
    """
    seen: set[str] = set()
    cur = by_id.get(obs.get("parentObservationId") or "")
    while cur is not None:
        cid = cur.get("id") or ""
        if cid in seen:  # defensive: a cycle would otherwise hang ingestion
            break
        seen.add(cid)
        if str(cur.get("type") or "").upper() == "TOOL":
            return cur.get("name") or "unknown_tool"
        if cur.get("name") == _AGENT_NODE_NAME:
            return AGENT_COMPONENT
        cur = by_id.get(cur.get("parentObservationId") or "")
    return OTHER_COMPONENT


def parse_observations(
    observations: Optional[list[dict[str, Any]]],
) -> Optional[dict[str, Any]]:
    """Aggregate a trace's generation observations into usage + cost.

    Returns None when there is nothing to aggregate, which tells ``parse_trace``
    to fall back to the message stream. ``tool_*`` is defined as "everything the
    agent did not spend itself" (total minus agent), so the two always add up to
    the total no matter how the components are labelled.
    """
    if not observations:
        return None
    by_id = {o.get("id") or "": o for o in observations if isinstance(o, dict)}
    gens = [
        o
        for o in observations
        if isinstance(o, dict)
        and str(o.get("type") or "").upper() in ("GENERATION", "EMBEDDING")
    ]
    if not gens:
        return None

    t_in = t_out = t_total = t_cache = 0
    a_in = a_out = a_total = a_cache = 0
    cost = a_cost = 0.0
    tokens_by_component: dict[str, int] = {}
    cost_by_component: dict[str, float] = {}

    for o in gens:
        i, out, total, cache = _obs_usage(o)
        c = _obs_cost(o)
        t_in += i
        t_out += out
        t_total += total
        t_cache += cache
        cost += c

        component = _component(o, by_id)
        tokens_by_component[component] = (
            tokens_by_component.get(component, 0) + total
        )
        cost_by_component[component] = (
            cost_by_component.get(component, 0.0) + c
        )
        if component == AGENT_COMPONENT:
            a_in += i
            a_out += out
            a_total += total
            a_cache += cache
            a_cost += c

    return {
        # columns
        "turn_input_tokens": t_in,
        "turn_output_tokens": t_out,
        "turn_tokens": t_total,
        "agent_tokens": a_total,
        "tool_tokens": t_total - a_total,
        "agent_cost": round(a_cost, 10),
        "tool_cost": round(cost - a_cost, 10),
        "generation_count": len(gens),
        # derived
        "cache_read_tokens": t_cache,
        "agent_input_tokens": a_in,
        "agent_output_tokens": a_out,
        "agent_cache_read_tokens": a_cache,
        "tokens_by_component": tokens_by_component,
        "cost_by_component": {
            k: round(v, 10) for k, v in cost_by_component.items()
        },
        "observation_cost": round(cost, 10),
    }


# --------------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------------- #
# Column-valued keys produced by parse_trace (everything else goes to `derived`).
COLUMN_KEYS = frozenset(
    {
        "prompt",
        "answer",
        "turn_input_tokens",
        "turn_output_tokens",
        "turn_tokens",
        "turn_tool_calls",
        "has_answer",
        "answer_finish_reason",
        "answer_is_refusal",
        "had_tool_call",
        "tool_error_count",
        "outcome",
        "aoi_name",
        "aoi_type",
        "primary_dataset_name",
        "has_insight",
        "is_global",
        "insight_id",
        "total_cost",
        "agent_tokens",
        "tool_tokens",
        "agent_cost",
        "tool_cost",
        "generation_count",
    }
)


def parse_trace(
    trace: dict[str, Any],
    observations: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Parse one trace into ``{<column>: value, ..., "derived": {...},
    "recognized_contract": bool, "parser_version": int}``.

    ``observations`` is the trace's observation list (see
    ``LangfuseClient.fetch_observations_window``). When supplied, its
    generations are the source of the token columns and of the agent/tool
    split; when omitted, the token columns fall back to the message stream and
    the split is left null. ``derived.usage_source`` records which happened.

    Identity/raw/timestamp fields are added by the ingest layer, not here.
    """
    output = _as_state_dict(trace.get("output"))
    state = parse_state(output)
    msgs = output.get("messages") if isinstance(output, dict) else None
    inp = _as_state_dict(trace.get("input")) or {}
    in_msgs = inp.get("messages") if isinstance(inp, dict) else None
    msg = parse_messages(msgs or [], in_msgs or [])

    combined = {**state, **msg}

    usage = parse_observations(observations)
    if usage is None:
        combined["usage_source"] = "messages"
        # No observations: the message-derived counts stand, but they only
        # cover the agent's own calls, so the split would be a lie.
        combined["total_cost"] = trace.get("totalCost")
    else:
        # The message-derived agent figure is kept alongside: the two are
        # independent measurements of the same calls, so a divergence is a
        # drift signal (they matched to the token on the validation trace).
        from_messages = combined.get("turn_tokens")
        combined["agent_tokens_from_messages"] = from_messages
        combined["usage_source"] = "observations"
        combined.update(usage)
        # The agent/tool split hinges on the LangGraph model node still being
        # named ``model`` (see _component). Rename it upstream and every call
        # silently becomes "other" — which a fill-rate check cannot catch,
        # because zero is not null. This flag can: it goes False.
        combined["usage_split_agrees"] = (
            usage["agent_tokens"] == from_messages if from_messages else None
        )
        # ``trace.totalCost`` is frequently null even when the observations
        # underneath it are priced, so the observation sum is the fallback.
        trace_cost = trace.get("totalCost")
        combined["total_cost"] = (
            trace_cost if trace_cost is not None else usage["observation_cost"]
        )

    row = {k: combined[k] for k in COLUMN_KEYS if k in combined}
    derived = {k: v for k, v in combined.items() if k not in COLUMN_KEYS}
    derived.pop("recognized_contract", None)

    return {
        **row,
        "derived": derived,
        "recognized_contract": state["recognized_contract"],
        "parser_version": PARSER_VERSION,
    }
