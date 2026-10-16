"""Unit tests for src/api/services/langfuse/model_prices.py."""

import re

import pytest

from src.api.services.langfuse import model_prices as MP
from src.api.services.langfuse.parse import _obs_usage


def _spec(name):
    return next(d for d in MP.DEFINITIONS if d["modelName"] == name)


def test_every_tier_prices_the_keys_zeno_reports():
    """The usage keys the LangChain handler and the executor span send. A key
    without a price is costed at $0, which is the bug these definitions fix."""
    for spec in MP.DEFINITIONS:
        for tier in spec["pricingTiers"]:
            for key in (
                "input",
                "input_cache_read",
                "output",
                "output_reasoning",
            ):
                assert tier["prices"].get(key), (spec["modelName"], key)


def test_prices_are_per_token():
    prices = _spec("gemini-3-flash-preview")["pricingTiers"][0]["prices"]
    assert prices["input"] == pytest.approx(0.50e-6)
    assert prices["input_cache_read"] == pytest.approx(0.05e-6)
    assert prices["output"] == pytest.approx(3.00e-6)


def test_cost_of_a_cached_call_matches_google_pricing():
    """A real gemini-3.1-pro-preview call shape, priced by hand from Google's
    page: $2.00 input, $0.20 cached, $12.00 output per 1M tokens."""
    usage = {
        "input": 2047,
        "input_cache_read": 18666,
        "output": 20,
        "output_reasoning": 655,
    }
    prices = _spec("gemini-3.1-pro-preview")["pricingTiers"][0]["prices"]
    cost = sum(prices[k] * v for k, v in usage.items())
    expected = (2047 * 2.00 + 18666 * 0.20 + 675 * 12.00) / 1e6
    assert cost == pytest.approx(expected)
    # And the parser reads the same call back as the full prompt.
    assert _obs_usage({"usageDetails": usage})[0] == 2047 + 18666


def test_match_pattern_matches_the_model_name_only():
    pattern = _spec("gemini-3.1-pro-preview")["matchPattern"]
    assert re.match(pattern, "gemini-3.1-pro-preview")
    assert re.match(pattern, "google/Gemini-3.1-Pro-Preview")
    assert not re.match(pattern, "gemini-3x1-pro-preview")
    assert not re.match(pattern, "gemini-3.1-pro-preview-tts")


def test_large_context_tier_applies_over_200k_prompt_tokens():
    tiers = _spec("gemini-3.1-pro-preview")["pricingTiers"]
    default = [t for t in tiers if t["isDefault"]]
    large = [t for t in tiers if not t["isDefault"]]
    assert len(default) == 1 and default[0]["conditions"] == []
    assert large[0]["conditions"][0]["value"] == 200000
    assert large[0]["prices"]["input"] == pytest.approx(4.00e-6)


def test_plan_creates_missing_and_overrides_built_in():
    existing = [
        {"modelName": "gemini-3-flash-preview", "isLangfuseManaged": True}
    ]
    by_name = {c.model_name: c for c in MP.plan(existing)}
    assert by_name["gemini-3.1-pro-preview"].action == "create"
    assert by_name["gemini-3-flash-preview"].action == "create"
    assert by_name["gemini-3-flash-preview"].reason == "overrides built-in"


def test_plan_skips_a_model_that_has_a_custom_definition():
    """Langfuse has no update call, so a re-run must not stack duplicates."""
    existing = [
        {"modelName": d["modelName"], "isLangfuseManaged": False}
        for d in MP.DEFINITIONS
    ]
    assert {c.action for c in MP.plan(existing)} == {"skip"}


# A definition made by hand in the Langfuse UI, as staging had it: input and
# output priced, nothing else.
_HAND_MADE_FLASH = {
    "id": "old",
    "modelName": "gemini-3-flash-preview",
    "matchPattern": "(?i)^(gemini-3-flash-preview)$",
    "isLangfuseManaged": False,
    "unit": "TOKENS",
    "pricingTiers": [
        {
            "id": "old_tier",
            "name": "Standard",
            "isDefault": True,
            "priority": 0,
            "conditions": [],
            "prices": {"input": 0.5e-6, "output": 3e-6},
        }
    ],
}


def test_diff_shows_the_unpriced_keys_of_a_hand_made_definition():
    lines = MP.diff(_HAND_MADE_FLASH, _spec("gemini-3-flash-preview"))
    assert "Standard.output_reasoning: none -> $3/1M" in lines
    assert "Standard.input_cache_read: none -> $0.05/1M" in lines
    # The prices it does have are right, so they are not listed.
    assert not any(line.startswith("Standard.input:") for line in lines)


def test_diff_reads_the_flat_price_shape():
    flat = {
        "modelName": "gemini-3-flash-preview",
        "matchPattern": _spec("gemini-3-flash-preview")["matchPattern"],
        "inputPrice": 0.5e-6,
        "outputPrice": 3e-6,
    }
    lines = MP.diff(flat, _spec("gemini-3-flash-preview"))
    assert "Standard.output_reasoning: none -> $3/1M" in lines


def test_a_differing_custom_definition_is_skipped_unless_replace():
    skip = MP.plan([_HAND_MADE_FLASH])
    flash = next(c for c in skip if c.model_name == "gemini-3-flash-preview")
    assert flash.action == "skip"
    assert flash.diff  # the reader still sees why

    replace = MP.plan([_HAND_MADE_FLASH], replace=True)
    flash = next(
        c for c in replace if c.model_name == "gemini-3-flash-preview"
    )
    assert flash.action == "replace"
    assert [m["id"] for m in flash.replaces] == ["old"]


def test_a_matching_custom_definition_is_skipped_even_with_replace():
    ours = {**_spec("gemini-3-flash-preview"), "isLangfuseManaged": False}
    changes = MP.plan([ours], replace=True)
    flash = next(
        c for c in changes if c.model_name == "gemini-3-flash-preview"
    )
    assert flash.action == "skip"


def test_replace_deletes_before_it_creates(monkeypatch):
    """Langfuse rejects a second custom definition with the same name."""
    calls = []
    monkeypatch.setattr(
        MP, "delete_model", lambda c, i: calls.append(("delete", i))
    )
    monkeypatch.setattr(
        MP, "create_model", lambda c, s: calls.append(("create", s)) or "new"
    )
    spec = _spec("gemini-3-flash-preview")
    assert MP.replace_model(None, [_HAND_MADE_FLASH], spec) == "new"
    assert calls == [("delete", "old"), ("create", spec)]


def test_a_failed_replace_restores_the_old_definition(monkeypatch):
    created = []

    def create(client, spec):
        if spec is _spec("gemini-3-flash-preview"):
            raise RuntimeError("400 Invalid request data")
        created.append(spec)
        return "restored"

    monkeypatch.setattr(MP, "delete_model", lambda c, i: None)
    monkeypatch.setattr(MP, "create_model", create)
    with pytest.raises(RuntimeError, match="400"):
        MP.replace_model(
            None, [_HAND_MADE_FLASH], _spec("gemini-3-flash-preview")
        )

    [restored] = created
    assert restored["modelName"] == "gemini-3-flash-preview"
    assert restored["matchPattern"] == _HAND_MADE_FLASH["matchPattern"]
    # Rebuilt without the server-side ids, which a create request rejects.
    assert "id" not in restored
    assert "id" not in restored["pricingTiers"][0]
    assert restored["pricingTiers"][0]["prices"] == {
        "input": 0.5e-6,
        "output": 3e-6,
    }
