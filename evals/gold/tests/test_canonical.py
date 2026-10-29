"""Identity semantics: the uid must move when the test changes and only then."""

from goldset.canonical import (
    UID_LENGTH,
    canonical_payload,
    case_uid,
    caseset_version,
)

QUERY = "How much tree cover loss in Brazil in 2022?"
EXPECTED = {"dataset_id": "4", "answer": "2.9 Mha", "aoi_ids": "BRA"}


def test_uid_shape():
    uid = case_uid(QUERY, EXPECTED)
    assert len(uid) == UID_LENGTH
    assert all(c in "0123456789abcdef" for c in uid)


def test_uid_stable_under_key_order():
    reordered = {"answer": "2.9 Mha", "aoi_ids": "BRA", "dataset_id": "4"}
    assert case_uid(QUERY, EXPECTED) == case_uid(QUERY, reordered)


def test_uid_ignores_surrounding_whitespace_and_crlf():
    assert case_uid(f"  {QUERY}\r\n", EXPECTED) == case_uid(QUERY, EXPECTED)
    padded = {**EXPECTED, "answer": "2.9 Mha  "}
    assert case_uid(QUERY, padded) == case_uid(QUERY, EXPECTED)


def test_empty_expected_values_do_not_affect_uid():
    with_blank = {**EXPECTED, "context_layer": "", "start_date": "  "}
    assert case_uid(QUERY, with_blank) == case_uid(QUERY, EXPECTED)


def test_uid_changes_on_expected_value_change():
    changed = {**EXPECTED, "answer": "3.1 Mha"}
    assert case_uid(QUERY, changed) != case_uid(QUERY, EXPECTED)


def test_uid_changes_on_query_change():
    assert case_uid(QUERY + " please", EXPECTED) != case_uid(QUERY, EXPECTED)


def test_uid_changes_when_expectation_added():
    grown = {**EXPECTED, "context_layer": "primary_forest"}
    assert case_uid(QUERY, grown) != case_uid(QUERY, EXPECTED)


def test_canonical_payload_is_valid_deterministic_json():
    import json

    payload = canonical_payload(QUERY, EXPECTED)
    parsed = json.loads(payload)
    assert parsed["query"] == QUERY
    assert parsed["expected"]["dataset_id"] == "4"


def test_caseset_version_order_insensitive():
    a, b, c = "a" * 16, "b" * 16, "c" * 16
    assert caseset_version([a, b, c]) == caseset_version([c, a, b])


def test_caseset_version_sensitive_to_membership_and_change():
    a, b, c = "a" * 16, "b" * 16, "c" * 16
    assert caseset_version([a, b]) != caseset_version([a, b, c])
    assert caseset_version([a, b]) != caseset_version([a, c])
