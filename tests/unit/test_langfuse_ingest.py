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
