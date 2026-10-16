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

from dataclasses import dataclass, field
from typing import Any, Optional

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
    action: str  # "create" | "replace" | "skip"
    reason: str
    # Custom definitions that "replace" deletes before it creates ours.
    replaces: list[dict[str, Any]] = field(default_factory=list)
    # How the existing custom definition differs from ours, one line each.
    diff: list[str] = field(default_factory=list)


def _tier_prices(model: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Prices per tier name, from either API shape.

    Newer instances return ``pricingTiers``. A definition made with the flat
    fields only has ``prices`` (``{key: {"price": p}}``) or
    ``inputPrice`` / ``outputPrice``.
    """
    tiers = model.get("pricingTiers") or []
    if tiers:
        return {
            t.get("name") or "?": dict(t.get("prices") or {}) for t in tiers
        }
    prices: dict[str, float] = {
        k: float(v["price"])
        for k, v in (model.get("prices") or {}).items()
        if isinstance(v, dict) and v.get("price") is not None
    }
    if not prices:
        for key, field_name in (
            ("input", "inputPrice"),
            ("output", "outputPrice"),
        ):
            if model.get(field_name) is not None:
                prices[key] = model[field_name]
    return {"Standard": prices}


def _fmt(price: Optional[float]) -> str:
    return "none" if price is None else f"${price / _PER_MILLION:g}/1M"


def diff(existing: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """How ``existing`` differs from ``spec``, as readable lines."""
    lines = []
    if existing.get("matchPattern") != spec["matchPattern"]:
        lines.append(
            f"matchPattern: {existing.get('matchPattern')!r} -> "
            f"{spec['matchPattern']!r}"
        )
    old = _tier_prices(existing)
    new = {t["name"]: t["prices"] for t in spec["pricingTiers"]}
    for tier in sorted(set(old) | set(new)):
        if tier not in new:
            lines.append(f"tier {tier!r}: removed")
            continue
        if tier not in old:
            lines.append(f"tier {tier!r}: added")
            continue
        for key in sorted(set(old[tier]) | set(new[tier])):
            a, b = old[tier].get(key), new[tier].get(key)
            if a is None or b is None or abs(a - b) > 1e-15:
                lines.append(f"{tier}.{key}: {_fmt(a)} -> {_fmt(b)}")
    return lines


def plan(
    existing: list[dict[str, Any]], replace: bool = False
) -> list[PlannedChange]:
    """Decide, per definition, whether to create, replace or skip it.

    Langfuse has no update call. A model that already has a custom definition
    is skipped unless ``replace`` is set; then the old custom definitions are
    deleted and ours is created (Langfuse rejects a second custom definition
    with the same name). A custom definition that already matches ours is
    skipped either way.
    """
    out = []
    for spec in DEFINITIONS:
        name = spec["modelName"]
        same = [m for m in existing if m.get("modelName") == name]
        custom = [m for m in same if not m.get("isLangfuseManaged")]
        if not custom:
            reason = "overrides built-in" if same else "no definition"
            out.append(PlannedChange(name, "create", reason))
            continue
        lines = [line for m in custom for line in diff(m, spec)]
        if not lines and len(custom) == 1:
            out.append(
                PlannedChange(name, "skip", "custom definition matches")
            )
        elif replace:
            out.append(
                PlannedChange(
                    name,
                    "replace",
                    f"{len(custom)} custom definition(s) differ",
                    replaces=custom,
                    diff=lines,
                )
            )
        else:
            out.append(
                PlannedChange(
                    name,
                    "skip",
                    "custom definition differs; use --replace",
                    diff=lines,
                )
            )
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


def delete_model(client: LangfuseClient, model_id: str) -> None:
    """Delete one custom definition. Built-in ones cannot be deleted."""
    with httpx.Client(timeout=client.timeout) as http:
        resp = http.delete(
            f"{client.host}{_MODELS_PATH}/{model_id}",
            auth=(client.public_key, client.secret_key),
        )
    _json_or_raise(resp, _MODELS_PATH)


def as_create_request(model: dict[str, Any]) -> dict[str, Any]:
    """A create request that rebuilds ``model``, as read from the API."""
    keep = (
        "modelName",
        "matchPattern",
        "unit",
        "startDate",
        "tokenizerId",
        "tokenizerConfig",
    )
    req = {k: model[k] for k in keep if model.get(k) is not None}
    tiers = model.get("pricingTiers") or []
    if tiers:
        req["pricingTiers"] = [
            {k: v for k, v in t.items() if k != "id"} for t in tiers
        ]
    else:
        for k in ("inputPrice", "outputPrice", "totalPrice"):
            if model.get(k) is not None:
                req[k] = model[k]
    return req


def replace_model(
    client: LangfuseClient,
    old: list[dict[str, Any]],
    spec: dict[str, Any],
) -> str:
    """Delete the ``old`` custom definitions, then create ``spec``.

    Between the two calls the model falls back to its built-in definition, or
    has no price; that is approximately one second. If the create fails, the
    old definitions are recreated from the copies read before the delete, and
    the error is raised.
    """
    for model in old:
        delete_model(client, model["id"])
    try:
        return create_model(client, spec)
    except Exception:
        for model in old:
            create_model(client, as_create_request(model))
        raise
