"""Resolve every ground-truth case before any trial runs.

Two failure classes, deliberately handled differently:

- the fetch itself failing -> **aborts the run**
- the selector not resolving against an otherwise-good response is recorded on
  the entry as ``unresolved`` and becomes a **row error at scoring time**. The
  fetch worked; this one case's metric is absent, which is a finding about that
  case rather than a reason to kill the run.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from goldset.groundtruth.client import AnalyticsClient, AnalyticsError, AnalyticsResult
from goldset.groundtruth.request import AnalyticsRequest, RequestError, build_request
from goldset.groundtruth.selector import SelectorError, apply_selector, parse_selector

GROUND_TRUTH_FIELD = "ground_truth"

DIGEST_LENGTH = 16
MAX_WORKERS = 8


def digest(values: list[float]) -> str:
    """A stable fingerprint of the fetched values from the analytics API.

    It hashes the **selected** values, not the whole response.

    ``repr`` rather than ``str`` so float precision survives, sorted so value
    order never matters.
    """
    payload = json.dumps(sorted(repr(v) for v in values), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


@dataclass(frozen=True)
class GroundTruth:
    """One case's fetched expectations, plus everything needed to audit them."""

    uid: str
    case_id: str
    selector: str
    values: list[float]
    digest: str
    request: AnalyticsRequest
    resource_id: str
    # The server's own echo of what it computed
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = ""
    # Set when the response was fine but the selector found no such metric.
    # Becomes a row error at scoring time, never a silent pass.
    unresolved: str | None = None

    def to_ledger(self) -> dict[str, Any]:
        """The per-entry ``ground_truth`` block written to the run record.

        ``dataset_id`` is recorded the TCL-based datasets share an endpoint.
        """
        record: dict[str, Any] = {
            "selector": self.selector,
            "values": self.values,
            "digest": self.digest,
            "dataset_id": self.request.dataset.dataset_id,
            "content_date_fixed": self.request.dataset.fixed,
            "resource_id": self.resource_id,
            "fetched_at": self.fetched_at,
            "request": {
                "endpoint": self.request.endpoint,
                "payload": self.request.payload,
            },
        }
        if self.metadata:
            record["metadata"] = self.metadata
        if self.unresolved:
            record["unresolved"] = self.unresolved
            # digest([]) is one constant for every unresolved case; two runs
            # sharing it would read as "same data" while proving nothing.
            del record["digest"]
        return record


def is_ground_truth(case: Any) -> bool:
    expected = getattr(case, "expected", {}) or {}
    return bool(str(expected.get(GROUND_TRUTH_FIELD) or "").strip())


def _resolve(case: Any, client: AnalyticsClient) -> GroundTruth:
    """Fetch and resolve one case. Raises on anything that should abort a run."""
    selector_text = case.expected[GROUND_TRUTH_FIELD].strip()
    selector = parse_selector(selector_text)  # malformed selector: abort
    request = build_request(case)  # unbuildable case: abort
    result: AnalyticsResult = client.fetch(request.endpoint, request.payload)

    values: list[float] = []
    unresolved: str | None = None
    try:
        values = [apply_selector(selector, result.result)]
    except SelectorError as exc:
        # The fetch succeeded; this case's metric is absent from the data.
        unresolved = str(exc)

    return GroundTruth(
        uid=case.uid,
        case_id=case.id,
        selector=selector.canonical(),
        values=values,
        digest=digest(values),
        request=request,
        resource_id=result.resource_id,
        metadata=result.metadata,
        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        unresolved=unresolved,
    )


def prefetch(
    cases: list[Any],
    client: AnalyticsClient,
    max_workers: int = MAX_WORKERS,
    verbose: bool = False,
) -> dict[str, GroundTruth]:
    """Resolve every ground-truth case, keyed by uid.

    Raises ``RequestError``, ``AnalyticsError`` or ``SelectorError`` (a selector
    that does not parse) on the first case that cannot be fetched — the caller
    aborts the run. Cases without a ``ground_truth``
    field are skipped entirely and never touched.
    """
    targets = [case for case in cases if is_ground_truth(case)]
    if not targets:
        return {}

    resolved: dict[str, GroundTruth] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(max_workers, len(targets)))
    ) as pool:
        futures = {pool.submit(_resolve, case, client): case for case in targets}
        try:
            for future in concurrent.futures.as_completed(futures):
                case = futures[future]
                ground_truth = future.result()  # re-raises to abort the run
                resolved[ground_truth.uid] = ground_truth
                if verbose:
                    detail = (
                        f"UNRESOLVED ({ground_truth.unresolved})"
                        if ground_truth.unresolved
                        else ", ".join(f"{v:,.2f}" for v in ground_truth.values)
                    )
                    print(f"    {case.id}  {ground_truth.selector} -> {detail}")
        except (RequestError, AnalyticsError, SelectorError):
            for future in futures:
                future.cancel()
            raise
    return resolved
