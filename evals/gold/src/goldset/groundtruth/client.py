"""The analytics API client: a two-hop async job, not a plain GET.

    1. POST the payload            -> {"status", "data": {"link": ...}}
    2. status == "pending"         -> re-POST the IDENTICAL payload (there is no
                                      GET-status endpoint), honouring Retry-After
    3. status in ("success","saved") -> GET data.link
                                      -> {"data": {"result": {col: [values]},
                                                   "metadata": {...}}}

Mirrors ``AnalyticsHandler`` in project-zeno so the harness asks the same
question the agent does.

The result resource id is a UUID5 over the payload, so identical requests reuse
one cached result; the API exposes no cache headers and no data-version field,
which is why the ledger records a digest of the fetched values instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://analytics.globalnaturewatch.org"
DEFAULT_TIMEOUT = 120.0
MAX_POLLS = 10
# Always use production analytics API
X_ENVIRONMENT = "production"
DONE = ("success", "saved")
FAILED = ("failed", "error")


def analytics_headers(token: str, environment: str = X_ENVIRONMENT) -> dict:
    """Headers every analytics request needs, wherever it is issued from.

    The default is production, because ground truth is the published data
    whichever agent deployment a run targets.
    """
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-environment": environment,
        "Authorization": f"Bearer {token}",
    }


# Deployments whose agent runs with GNW_STAGE=staging. Ephemeral deployments
# set it in terraform/ephemeral/variables.tf (env_config).
STAGING_ANALYTICS_ENVIRONMENTS = {"staging", "ephemeral"}


def agent_environment(run_environment: str) -> str:
    """Which analytics environment the agent under test reads from."""
    if run_environment in STAGING_ANALYTICS_ENVIRONMENTS:
        return "staging"
    return X_ENVIRONMENT


class AnalyticsError(Exception):
    """The analytics API couldn't answer. A run must abort loudly."""


@dataclass(frozen=True)
class AnalyticsResult:
    """One fetched response, plus what is needed to audit the verdict."""

    result: dict[str, list[Any]]
    metadata: dict[str, Any]
    link: str

    @property
    def resource_id(self) -> str:
        return self.link.rstrip("/").split("/")[-1]


class AnalyticsClient:
    def __init__(
        self,
        token: str,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_polls: int = MAX_POLLS,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_polls = max_polls
        self._headers = analytics_headers(token)
        self._timeout = timeout
        self._transport = transport

    def fetch(self, endpoint: str, payload: dict[str, Any]) -> AnalyticsResult:
        url = self.base_url + endpoint
        with httpx.Client(
            timeout=self._timeout, follow_redirects=True, transport=self._transport
        ) as client:
            body = self._submit(client, url, payload)
            link = (body.get("data") or {}).get("link")
            if not link:
                raise AnalyticsError(f"{endpoint}: no data.link in {body!r}")
            try:
                response = client.get(link, headers=self._headers)
                response.raise_for_status()
                data = response.json().get("data") or {}
            except httpx.HTTPError as exc:
                raise AnalyticsError(f"{link}: {exc}") from exc
            except ValueError as exc:  # includes json.JSONDecodeError
                raise AnalyticsError(f"{link}: malformed JSON ({exc})") from exc

        result = data.get("result")
        if not result:
            # an empty result is a failed fetch
            raise AnalyticsError(f"{endpoint}: empty result at {link}")
        return AnalyticsResult(result, data.get("metadata") or {}, link)

    def _submit(
        self, client: httpx.Client, url: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        for _ in range(self.max_polls):
            try:
                response = client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPError as exc:
                raise AnalyticsError(f"{url}: {exc}") from exc
            except ValueError as exc:  # includes json.JSONDecodeError
                raise AnalyticsError(f"{url}: malformed JSON ({exc})") from exc
            status = str(body.get("status") or "").lower()
            if status in DONE:
                return body
            if status in FAILED:
                raise AnalyticsError(f"{url}: job {status}: {body.get('message')}")
            if status != "pending":
                raise AnalyticsError(f"{url}: unexpected status {status!r}")
            time.sleep(float(response.headers.get("Retry-After", 1)))
        raise AnalyticsError(f"{url}: still pending after {self.max_polls} polls")
