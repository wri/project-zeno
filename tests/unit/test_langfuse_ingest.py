"""Unit tests for the Langfuse ingestion row builder
(src/api/services/langfuse/ingest.py).

Synthetic fixtures only (no real user text). Focus: NUL-byte sanitization, since
Postgres text/jsonb reject 0x00 and an unsanitized trace once aborted a batch.
"""

from src.api.services.langfuse.ingest import (
    _split_auxiliary,
    _strip_nul,
    build_row,
)
from src.shared.langfuse_tracing import AUXILIARY_TAG


def test_strip_nul_scrubs_nested_strings():
    payload = {
        "a": "clean",
        "b": "with\x00nul",
        "c": ["ok", "bad\x00", {"d": "deep\x00nul"}],
        "e": 42,
        "f": None,
    }
    out = _strip_nul(payload)
    assert out["b"] == "withnul"
    assert out["c"] == ["ok", "bad", {"d": "deepnul"}]
    # non-string scalars pass through untouched
    assert out["e"] == 42
    assert out["f"] is None


def test_strip_nul_scrubs_dict_keys():
    assert _strip_nul({"k\x00ey": "v"}) == {"key": "v"}


def test_strip_nul_leaves_clean_strings_identical():
    s = "no nul here"
    assert _strip_nul(s) is s


def test_build_row_strips_nul_from_identity_fields():
    # A NUL in a trace identity field must be scrubbed regardless of parse path.
    row = build_row(
        {"id": "t1", "userId": "user\x00id", "environment": "production"}
    )
    assert "\x00" not in row["user_id"]
    assert row["user_id"] == "userid"
    assert row["id"] == "t1"


def test_build_row_null_session_is_singleton_turn():
    # No sessionId => singleton thread; turn position is set directly (the
    # post-upsert recompute only touches session-scoped rows).
    row = build_row({"id": "t1", "environment": "production"})
    assert row["session_id"] is None
    assert row["turn_index"] == 1
    assert row["is_final_turn_in_thread"] is True


def test_build_row_session_turn_index_deferred_to_recompute():
    # With a session, turn position AND the per-turn diffs are cross-row and filled
    # by recompute; the builder leaves them None so a re-ingest doesn't assert a
    # stale ordinal/diff.
    row = build_row({"id": "t1", "sessionId": "s1"})
    assert row["turn_index"] is None
    assert row["is_final_turn_in_thread"] is None
    assert row["insight_created_this_turn"] is None
    assert row["datasets_analysed_this_turn"] is None


def test_build_row_singleton_diffs_reflect_this_turn():
    # A singleton (null-session) turn has no predecessor: any insight it carries is
    # created this turn and every cumulative dataset is new this turn.
    row = build_row(
        {
            "id": "t1",
            "output": {
                "messages": [],
                "insight_id": "ins1",
                "statistics": [{"dataset_name": "gfw"}],
            },
        }
    )
    assert row["session_id"] is None
    assert row["insight_created_this_turn"] is True
    assert row["datasets_analysed_this_turn"] == ["gfw"]


def test_build_row_singleton_without_insight_has_empty_diffs():
    # No insight, no datasets => diffs are the empty defaults (not None).
    row = build_row({"id": "t1", "environment": "production"})
    assert row["insight_created_this_turn"] is False
    assert row["datasets_analysed_this_turn"] == []


# --------------------------------------------------------------------------- #
# auxiliary traces (LLM calls that are not agent turns)
# --------------------------------------------------------------------------- #
def test_auxiliary_traces_are_dropped_from_the_turn_table():
    """Thread naming and the like carry no AgentState, so ingesting them would
    add zero-token EMPTY rows and drag every per-turn average down."""
    turns, dropped = _split_auxiliary(
        [
            {"id": "turn", "tags": []},
            {"id": "naming", "tags": [AUXILIARY_TAG]},
            {"id": "no_tags_field"},
        ]
    )
    assert [t["id"] for t in turns] == ["turn", "no_tags_field"]
    assert dropped == 1


def test_build_row_records_usage_from_observations():
    """The row's token columns come from the observations when they are given."""
    trace = {
        "id": "t1",
        "sessionId": None,
        "output": {"messages": []},
        "totalCost": None,
    }
    observations = [
        {"id": "root", "type": "CHAIN", "name": "LangGraph"},
        {
            "id": "m",
            "type": "CHAIN",
            "name": "model",
            "parentObservationId": "root",
        },
        {
            "id": "g",
            "type": "GENERATION",
            "parentObservationId": "m",
            "usageDetails": {"input": 100, "output": 10, "total": 110},
            "totalCost": 0.002,
        },
    ]
    row = build_row(trace, observations)
    assert row["turn_tokens"] == 110
    assert row["agent_tokens"] == 110
    assert row["tool_tokens"] == 0
    # trace.totalCost was null; the observation sum stands in for it.
    assert row["total_cost"] == 0.002


def test_build_row_without_observations_keeps_message_usage():
    trace = {"id": "t1", "sessionId": None, "output": {"messages": []}}
    row = build_row(trace)
    assert row["derived"]["usage_source"] == "messages"


def test_observation_fetch_asks_for_every_type_and_pads_the_window():
    """Two things this must not regress: `obs_type=None` (attribution needs the
    ancestor spans) and the upper pad (a trace at the window's edge has children
    that start after it closes)."""
    import asyncio
    from datetime import datetime, timezone

    from src.api.services.langfuse.ingest import (
        OBSERVATION_WINDOW_PAD,
        _fetch_observations,
    )

    recorded = {}

    class _Client:
        def fetch_observations_window(
            self, from_ts, to_ts, environment, page_size, obs_type
        ):
            recorded.update(
                from_ts=from_ts,
                to_ts=to_ts,
                obs_type=obs_type,
            )
            return [
                {"id": "a", "traceId": "keep"},
                {"id": "b", "traceId": "from_an_earlier_window"},
            ]

    from_ts = datetime(2026, 9, 1, tzinfo=timezone.utc)
    to_ts = datetime(2026, 9, 2, tzinfo=timezone.utc)
    grouped = asyncio.run(
        _fetch_observations(_Client(), from_ts, to_ts, None, 50, {"keep"})
    )

    assert recorded["obs_type"] is None
    assert recorded["to_ts"] == to_ts + OBSERVATION_WINDOW_PAD
    # Observations of traces this window did not fetch are discarded.
    assert set(grouped) == {"keep"}


def test_observation_fetch_failure_degrades_instead_of_raising():
    import asyncio
    from datetime import datetime, timezone

    from src.api.services.langfuse.fetch import LangfuseFetchError
    from src.api.services.langfuse.ingest import _fetch_observations

    class _Client:
        def fetch_observations_window(self, *a, **kw):
            raise LangfuseFetchError("langfuse 500")

    grouped = asyncio.run(
        _fetch_observations(
            _Client(),
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 2, tzinfo=timezone.utc),
            None,
            50,
            {"t"},
        )
    )
    # Empty, not an exception: the window still ingests on message-derived usage.
    assert grouped == {}
