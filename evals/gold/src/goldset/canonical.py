"""Content-addressed identity for GOLD cases.

A case's ``uid`` is a truncated SHA-256 over a canonical JSON serialisation
of its query plus every non-empty expectation. Editing the prompt or any
expected value therefore mints a new uid; metadata (status, group, notes)
does not participate, so triage annotations never masquerade as a new
version of the test.

A multi-turn case's uid covers every turn's query and expectations, in order.
In v2 it also covers each turn's ``deltas``. v1 is frozen and its uids do not,
so they never change (see ``conversation_uid``).

The ``caseset_version`` is a hash over the sorted uids of every case in the
store: any edit to any case, or adding/removing one, changes the set
version. Results ledgers key on both, so a score is always pinned to the
exact case content it ran against.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping

UID_LENGTH = 16


def normalize_text(value: object) -> str:
    """Normalise a value for hashing: str, unified newlines, stripped."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def canonical_payload(query: str, expected: Mapping[str, object]) -> str:
    """Deterministic JSON string a case uid is computed over.

    Empty expectations are dropped, so adding an empty key to a case never
    changes its identity. Key order never matters.
    """
    clean = {key: normalize_text(value) for key, value in expected.items()}
    clean = {key: value for key, value in clean.items() if value}
    payload = {"expected": clean, "query": normalize_text(query)}
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def case_uid(query: str, expected: Mapping[str, object]) -> str:
    """uid = sha256(canonical payload), truncated to UID_LENGTH hex chars."""
    digest = hashlib.sha256(
        canonical_payload(query, expected).encode("utf-8")
    ).hexdigest()
    return digest[:UID_LENGTH]


def canonical_deltas(deltas: object) -> dict[str, list[str]]:
    """A turn's delta assertions in canonical form: each kind's field names
    normalised, de-duplicated and sorted, empty kinds dropped. Key order,
    list order and repeats never change what ``evaluate_deltas`` scores, so
    they must never mint a version either."""
    if not isinstance(deltas, Mapping):
        return {}
    clean = {}
    for kind, fields in deltas.items():
        if not isinstance(fields, (list, tuple)):
            fields = [fields]
        names = sorted({normalize_text(name) for name in fields} - {""})
        if names:
            clean[str(kind)] = names
    return clean


def conversation_uid(
    turns: Iterable[Mapping[str, object]], include_deltas: bool = False
) -> str:
    """uid for a multi-turn case: hash over every turn's query + expected,
    **in order** — turn order is test content, so reordering turns mints a
    new version. Metadata never participates.

    What else the uid covers depends on the store, via its MANIFEST.json
    ``uid_includes_deltas`` flag (``include_deltas`` here):

    - flag absent/False: queries + expected only. Delta assertions are
      scored but do not participate in the uid.
    - flag True (the current store, cases/v2): each turn's non-empty
      ``deltas`` participate too, in ``canonical_deltas`` form, so editing a
      delta assertion mints a new version while reordering its keys or
      field lists does not.
    """
    turn_payloads = []
    for turn in turns:
        payload = json.loads(
            canonical_payload(
                str(turn.get("query", "")),
                turn.get("expected") or {},  # type: ignore[arg-type]
            )
        )
        deltas = canonical_deltas(turn.get("deltas")) if include_deltas else {}
        if deltas:
            payload["deltas"] = deltas
        turn_payloads.append(payload)
    payload = json.dumps(
        turn_payloads,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:UID_LENGTH]


def caseset_version(uids: Iterable[str]) -> str:
    """Version of the whole set: hash of the sorted uids, order-insensitive."""
    joined = "\n".join(sorted(uids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:UID_LENGTH]
