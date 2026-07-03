"""Unit tests for the Langfuse ingestion row builder
(src/api/services/langfuse/ingest.py).

Synthetic fixtures only (no real user text). Focus: NUL-byte sanitization, since
Postgres text/jsonb reject 0x00 and an unsanitized trace once aborted a batch.
"""

from src.api.services.langfuse.ingest import _strip_nul, build_row


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
