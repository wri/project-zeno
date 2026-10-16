"""Custom Langfuse model definitions for the Gemini models Zeno calls.

Langfuse calculates a call's cost from its model-definition table, which each
instance keeps for itself. Two gaps make cost per query read low:

* A model with no definition is stored with usage and **zero cost**. The
  Gemini 3.1 preview models had none on Langfuse 3.152.0.
* A definition prices named usage keys only. The built-in Gemini definitions
  price ``input_cached_tokens``, but the LangChain handler and the code
  executor span report cached prompt tokens as ``input_cache_read``, so
  cached tokens cost $0.

``DEFINITIONS`` closes both. A custom definition with the same model name
overrides the built-in one, so each definition repeats every key.

Langfuse prices a call when it receives it. A new definition does not change
earlier calls, so re-ingesting does not recover their cost.

Prices are from https://ai.google.dev/gemini-api/docs/pricing (Standard, paid
tier), read 2026-10-16. Update them here when Google changes them, then run
``langfuse-sync-model-prices`` on each instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from src.api.services.langfuse.fetch import LangfuseClient, _json_or_raise

_MODELS_PATH = "/api/public/models"
_PER_MILLION = 1e-6


def _prices(input_: float, cached: float, output: float) -> dict[str, float]:
    """Per-token prices from per-million ones, for every key a call may report.

    The first key of each group is the one Zeno's calls report. The others
    are the names Gemini and the built-in definitions use, so a call reported
    either way is priced. Thinking tokens are billed as output.
    """
    inp, cache, out = (p * _PER_MILLION for p in (input_, cached, output))
    return {
        "input": inp,
        "prompt_token_count": inp,
        "input_cache_read": cache,
        "input_cached_tokens": cache,
        "cached_content_token_count": cache,
        "output": out,
        "output_reasoning": out,
        "candidates_token_count": out,
        "thoughts_token_count": out,
    }


def _definition(name: str, *tiers: dict[str, Any]) -> dict[str, Any]:
    return {
        "modelName": name,
        "matchPattern": f"(?i)^(google/)?({name.replace('.', '[.]')})$",
        "unit": "TOKENS",
        "pricingTiers": list(tiers),
    }


def _standard(prices: dict[str, float]) -> dict[str, Any]:
    return {
        "name": "Standard",
        "isDefault": True,
        "priority": 0,
        "conditions": [],
        "prices": prices,
    }


# Google bills prompts over 200k tokens at the higher rate. Same condition as
# the built-in Gemini 2.5 Pro definition.
_LARGE_CONTEXT = {
    "usageDetailPattern": "(input|prompt|cached)",
    "operator": "gt",
    "value": 200000,
    "caseSensitive": False,
}

DEFINITIONS: list[dict[str, Any]] = [
    _definition(
        "gemini-3.1-pro-preview",
        _standard(_prices(2.00, 0.20, 12.00)),
        {
            "name": "Large Context",
            "isDefault": False,
            "priority": 1,
            "conditions": [_LARGE_CONTEXT],
            "prices": _prices(4.00, 0.40, 18.00),
        },
    ),
    _definition(
        "gemini-3.1-flash-lite-preview", _standard(_prices(0.25, 0.025, 1.50))
    ),
    # Overrides the built-in definition, which has no input_cache_read price.
    _definition(
        "gemini-3-flash-preview", _standard(_prices(0.50, 0.05, 3.00))
    ),
]


@dataclass
class PlannedChange:
    model_name: str
    action: str  # "create" | "skip"
    reason: str


def plan(existing: list[dict[str, Any]]) -> list[PlannedChange]:
    """Decide, per definition, whether to create it.

    A model that already has a custom definition is skipped: Langfuse has no
    update call, and a second custom definition would only win by being newer.
    To change a price, delete the custom definition in Langfuse first.
    """
    out = []
    for spec in DEFINITIONS:
        name = spec["modelName"]
        same = [m for m in existing if m.get("modelName") == name]
        custom = [m for m in same if not m.get("isLangfuseManaged")]
        if custom:
            out.append(PlannedChange(name, "skip", "custom definition exists"))
        elif same:
            out.append(PlannedChange(name, "create", "overrides built-in"))
        else:
            out.append(PlannedChange(name, "create", "no definition"))
    return out


def list_models(client: LangfuseClient) -> list[dict[str, Any]]:
    """Every model definition on the instance, built-in and custom."""
    models: list[dict[str, Any]] = []
    page = 1
    with httpx.Client(timeout=client.timeout) as http:
        while True:
            resp = http.get(
                client.host + _MODELS_PATH,
                params={"page": page, "limit": 100},
                auth=(client.public_key, client.secret_key),
            )
            data = _json_or_raise(resp, _MODELS_PATH)
            models.extend(data.get("data") or [])
            total = (data.get("meta") or {}).get("totalPages") or 1
            if page >= total:
                return models
            page += 1


def create_model(client: LangfuseClient, spec: dict[str, Any]) -> str:
    """Create one definition and return its id."""
    with httpx.Client(timeout=client.timeout) as http:
        resp = http.post(
            client.host + _MODELS_PATH,
            json=spec,
            auth=(client.public_key, client.secret_key),
        )
    return _json_or_raise(resp, _MODELS_PATH).get("id", "")
