"""OpenRouter backend registration in src.agent.llms.

The registry is built at import time, so these call the builder directly
rather than reloading the module (importing llms has side effects).
"""

import pytest
from langchain_openai import ChatOpenAI

from src.agent.config import AgentSettings
from src.agent.llms import (
    build_openrouter_models,
    openrouter_slug,
    parse_openrouter_entry,
)


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("deepseek/deepseek-v4-pro", "or:deepseek-v4-pro"),
        ("z-ai/glm-5.3", "or:glm-5.3"),
        ("openai/gpt-oss-120b", "or:gpt-oss-120b"),
        # No vendor prefix: the whole ID becomes the slug body.
        ("some-model", "or:some-model"),
    ],
)
def test_slug_drops_the_vendor_prefix(model_id, expected):
    assert openrouter_slug(model_id) == expected


def test_unset_registers_nothing(monkeypatch):
    monkeypatch.setattr(AgentSettings, "openrouter_models", "")
    assert build_openrouter_models() == {}


def test_whitespace_only_registers_nothing(monkeypatch):
    monkeypatch.setattr(AgentSettings, "openrouter_models", "   ")
    assert build_openrouter_models() == {}


def test_models_without_api_key_raise(monkeypatch):
    monkeypatch.setattr(
        AgentSettings, "openrouter_models", "deepseek/deepseek-v4-pro"
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_openrouter_models()


def test_builds_one_chat_model_per_id(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(
        AgentSettings,
        "openrouter_models",
        # Trailing comma and stray spaces are tolerated.
        " deepseek/deepseek-v4-pro , z-ai/glm-5.3 ,",
    )
    monkeypatch.setattr(
        AgentSettings, "openrouter_base_url", "https://openrouter.ai/api/v1"
    )
    monkeypatch.setattr(AgentSettings, "openrouter_max_tokens", 16_384)

    models = build_openrouter_models()

    assert sorted(models) == ["or:deepseek-v4-pro", "or:glm-5.3"]
    deepseek = models["or:deepseek-v4-pro"]
    assert isinstance(deepseek, ChatOpenAI)
    assert deepseek.model_name == "deepseek/deepseek-v4-pro"
    assert str(deepseek.openai_api_base) == "https://openrouter.ai/api/v1"
    assert deepseek.max_tokens == 16_384
    assert deepseek.temperature == 0
    assert models["or:glm-5.3"].model_name == "z-ai/glm-5.3"


def test_base_url_is_configurable(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(AgentSettings, "openrouter_models", "vendor/model")
    monkeypatch.setattr(
        AgentSettings, "openrouter_base_url", "https://proxy.example/v1"
    )
    model = build_openrouter_models()["or:model"]
    assert str(model.openai_api_base) == "https://proxy.example/v1"


@pytest.mark.parametrize(
    "entry,model_id,providers",
    [
        ("vendor/model", "vendor/model", []),
        ("vendor/model@google-vertex", "vendor/model", ["google-vertex"]),
        (
            "vendor/model@google-vertex+parasail",
            "vendor/model",
            ["google-vertex", "parasail"],
        ),
        # stray separators and spaces are tolerated
        (" vendor/model @ parasail + ", "vendor/model", ["parasail"]),
    ],
)
def test_parse_entry_splits_model_from_providers(entry, model_id, providers):
    assert parse_openrouter_entry(entry) == (model_id, providers)


def test_pinned_slug_keeps_the_first_provider():
    """So a pinned and a default-routed variant can coexist for comparison."""
    assert openrouter_slug("meta-llama/llama-4-maverick") == (
        "or:llama-4-maverick"
    )
    assert (
        openrouter_slug(
            "meta-llama/llama-4-maverick", ["google-vertex", "parasail"]
        )
        == "or:llama-4-maverick@google-vertex"
    )


def test_pinning_sets_provider_routing(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(
        AgentSettings,
        "openrouter_models",
        "meta-llama/llama-4-maverick@google-vertex+parasail,z-ai/glm-5.3",
    )
    models = build_openrouter_models()

    assert sorted(models) == [
        "or:glm-5.3",
        "or:llama-4-maverick@google-vertex",
    ]
    pinned = models["or:llama-4-maverick@google-vertex"]
    assert pinned.extra_body == {
        "provider": {
            "only": ["google-vertex", "parasail"],
            "allow_fallbacks": True,
        }
    }
    # An unpinned entry must not carry provider routing at all.
    assert not (models["or:glm-5.3"].extra_body or {}).get("provider")
