"""Resilient client for the Langfuse ``/api/public/traces`` list endpoint.

Design notes (validated against the staging instance, which 500s / hits
ClickHouse memory limits under load):

* Fetch over **closed, ascending time windows** (``fromTimestamp``/
  ``toTimestamp`` + ``orderBy=timestamp.asc``). Never page-number over an
  open-ended ``desc`` set — new traces arriving mid-run would shift offsets and
  silently skip rows.
* Retry 429 (honouring ``Retry-After``) and network errors with backoff.
* On persistent 5xx, **halve the page size (floor 1) and restart the window**;
  id-dedup makes the refetch safe. If it still fails at size 1, raise loudly
  (``LangfuseFetchError``) so the caller records a failed chunk rather than
  silently dropping data.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_TRACES_PATH = "/api/public/traces"


class LangfuseFetchError(RuntimeError):
    """Raised when a window cannot be fetched after retries + page-halving."""


class _ServerError(Exception):
    """Internal: a persistent 5xx for one page (triggers page-halving)."""


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _backoff(attempt: int) -> float:
    # exponential with jitter, capped
    return min(30.0, (2**attempt) + random.uniform(0, 1.0))


@dataclass
class LangfuseClient:
    host: str
    public_key: str
    secret_key: str
    timeout: float = 60.0
    max_retries: int = 6

    @classmethod
    def from_env(cls) -> "LangfuseClient":
        """Build from LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY (KeyError if missing)."""
        return cls(
            host=os.environ["LANGFUSE_HOST"].rstrip("/"),
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        )

    # -- public API -------------------------------------------------------- #
    def fetch_window(
        self,
        from_ts: datetime,
        to_ts: datetime,
        environment: Optional[str] = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Return all traces with ``from_ts <= timestamp < to_ts`` (ascending),
        de-duplicated by id. Raises ``LangfuseFetchError`` on unrecoverable
        failure."""
        limit = page_size
        with httpx.Client(timeout=self.timeout) as client:
            while True:
                try:
                    return self._fetch_all_pages(
                        client, from_ts, to_ts, environment, limit
                    )
                except _ServerError as e:
                    if limit <= 1:
                        raise LangfuseFetchError(
                            f"Langfuse 5xx at page size 1 for window "
                            f"[{_iso(from_ts)}, {_iso(to_ts)}): {e}"
                        ) from e
                    new_limit = max(1, limit // 2)
                    logger.warning(
                        "langfuse_fetch_halving_page_size",
                        old_limit=limit,
                        new_limit=new_limit,
                        window_start=_iso(from_ts),
                    )
                    limit = new_limit

    def fetch_trace(self, trace_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single trace by id (the cheap/reliable path). Returns the
        trace dict, or None if it doesn't exist (404). Raises
        ``LangfuseFetchError`` only on persistent transport/server failure."""
        url = f"{self.host}{_TRACES_PATH}/{trace_id}"
        attempt = 0
        with httpx.Client(timeout=self.timeout) as client:
            while True:
                try:
                    resp = client.get(
                        url, auth=(self.public_key, self.secret_key)
                    )
                except httpx.RequestError as e:
                    attempt += 1
                    if attempt > self.max_retries:
                        raise LangfuseFetchError(
                            f"network error fetching {trace_id}: {e}"
                        ) from e
                    time.sleep(_backoff(attempt))
                    continue

                if resp.status_code == 404:
                    return None
                if resp.status_code == 429 or resp.status_code >= 500:
                    attempt += 1
                    if attempt > self.max_retries:
                        raise LangfuseFetchError(
                            f"{resp.status_code} fetching {trace_id} "
                            f"past max_retries"
                        )
                    time.sleep(_retry_after(resp) or _backoff(attempt))
                    continue

                resp.raise_for_status()
                return resp.json()

    # -- internals --------------------------------------------------------- #
    def _fetch_all_pages(
        self,
        client: httpx.Client,
        from_ts: datetime,
        to_ts: datetime,
        environment: Optional[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self._get_page(
                client, page, limit, from_ts, to_ts, environment
            )
            rows = data.get("data") or []
            for r in rows:
                rid = r.get("id")
                if rid and rid not in seen:
                    seen.add(rid)
                    out.append(r)
            meta = data.get("meta") or {}
            total_pages = meta.get("totalPages")
            if not rows or (total_pages is not None and page >= total_pages):
                return out
            page += 1

    def _get_page(
        self,
        client: httpx.Client,
        page: int,
        limit: int,
        from_ts: datetime,
        to_ts: datetime,
        environment: Optional[str],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "limit": limit,
            "orderBy": "timestamp.asc",
            "fromTimestamp": _iso(from_ts),
            "toTimestamp": _iso(to_ts),
        }
        if environment:
            params["environment"] = environment

        attempt = 0
        server_errors = 0
        while True:
            try:
                resp = client.get(
                    self.host + _TRACES_PATH,
                    params=params,
                    auth=(self.public_key, self.secret_key),
                )
            except httpx.RequestError as e:
                attempt += 1
                if attempt > self.max_retries:
                    raise LangfuseFetchError(
                        f"network error after {attempt} attempts: {e}"
                    ) from e
                time.sleep(_backoff(attempt))
                continue

            if resp.status_code == 429:
                wait = _retry_after(resp) or _backoff(attempt)
                attempt += 1
                if attempt > self.max_retries:
                    raise LangfuseFetchError("rate-limited past max_retries")
                logger.warning("langfuse_rate_limited", wait_s=round(wait, 1))
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                server_errors += 1
                if server_errors > 2:
                    # let the window halve its page size
                    raise _ServerError(f"{resp.status_code} x{server_errors}")
                time.sleep(_backoff(server_errors))
                continue

            resp.raise_for_status()
            return resp.json()


def _retry_after(resp: httpx.Response) -> Optional[float]:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
