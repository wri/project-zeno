import os

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.agent.config import AgentSettings

load_dotenv()

# Anthropic
SONNET = ChatAnthropic(
    model="claude-sonnet-4-6",
    temperature=0,
    max_tokens=64_000,  # Sonnet has a limit of max 64000 tokens
)
HAIKU = ChatAnthropic(
    model="claude-haiku-4-5",
    temperature=0,
    max_tokens=8_192,  # Haiku has a limit of max 8192 tokens
)

# Google
GEMINI = ChatGoogleGenerativeAI(
    model="gemini-3.1-pro-preview",
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    thinking_level="low",
    max_retries=AgentSettings.llm_max_retries,
    timeout=300,
)
GEMINI_FLASH = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=AgentSettings.llm_max_retries,
    thinking_level="low",
    timeout=300,
)
GEMINI_FLASH_LITE = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite-preview",
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=AgentSettings.llm_max_retries,
    thinking_level="low",
    timeout=300,
)
# Latest Flash generation. Pinned to an explicit version, not the
# ``gemini-flash-latest`` alias: an alias silently changes what an eval run
# measured, so a recorded result could no longer be reproduced.
GEMINI_FLASH_38 = ChatGoogleGenerativeAI(
    model="gemini-3.8-flash",
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=AgentSettings.llm_max_retries,
    thinking_level="low",
    timeout=300,
)
# Single-shot classification (e.g. language detection in src.agent.language):
# minimal thinking cuts latency roughly in half vs. GEMINI_FLASH_LITE's "low"
# for tasks that need no reasoning at all, just a short constrained answer.
GEMINI_FLASH_LITE_MINIMAL = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite-preview",
    max_tokens=20,
    include_thoughts=False,
    max_retries=AgentSettings.llm_max_retries,
    thinking_level="minimal",
    timeout=30,
)
# OpenAI
# GPT = ChatOpenAI(
#     model="gpt-4o",
#     temperature=0,
#     max_tokens=None,  # max_tokens=None means no limit
# )

# OpenRouter
OPENROUTER_SLUG_PREFIX = "or:"


def parse_openrouter_entry(entry: str) -> tuple[str, list[str]]:
    """Split an OPENROUTER_MODELS entry into its model ID and provider pins.

    ``vendor/model`` -> ("vendor/model", []) and lets OpenRouter route.
    ``vendor/model@google-vertex+parasail`` pins the request to those
    providers, in that order.

    Pinning matters because OpenRouter routes one model across several
    providers whose capabilities differ. Two of the five that serve
    ``meta-llama/llama-4-maverick`` do not support tool calling at all, so
    a default-routed request can land somewhere that cannot run the agent.
    """
    model_id, _, providers = entry.partition("@")
    pins = [p.strip() for p in providers.split("+") if p.strip()]
    return model_id.strip(), pins


def openrouter_slug(model_id: str, providers: list[str] | None = None) -> str:
    """Registry slug for an OpenRouter model ID.

    ``deepseek/deepseek-v4-pro`` -> ``or:deepseek-v4-pro``. Slugs address
    the registry (MODEL, SMALL_MODEL, FALLBACK_MODELS); the full IDs go to
    OpenRouter. The prefix keeps these apart from the models above.

    A pinned entry keeps its first provider in the slug
    (``or:llama-4-maverick@google-vertex``) so a pinned and a default-routed
    variant of one model can both be registered and compared.
    """
    slug = OPENROUTER_SLUG_PREFIX + model_id.split("/", 1)[-1]
    return f"{slug}@{providers[0]}" if providers else slug


def build_openrouter_models() -> dict[str, BaseChatModel]:
    """One ChatOpenAI per ID in OPENROUTER_MODELS, keyed by slug.

    OpenRouter serves an OpenAI-compatible API, so ChatOpenAI needs only a
    base URL. Returns an empty dict when OPENROUTER_MODELS is unset, which
    is the default; raises when models are listed with no API key, because
    the alternative is a confusing 401 on the first agent turn.
    """
    raw = AgentSettings.openrouter_models.strip()
    if not raw:
        return {}
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise ValueError(
            "OPENROUTER_MODELS is set but OPENROUTER_API_KEY is not"
        )
    models: dict[str, BaseChatModel] = {}
    for entry in (part.strip() for part in raw.split(",")):
        if not entry:
            continue
        model_id, providers = parse_openrouter_entry(entry)
        if not model_id:
            continue
        extra_body: dict = {}
        if providers:
            # allow_fallbacks stays on, but "only" caps the candidates, so a
            # fallback can never reach a provider outside the pinned set.
            extra_body["provider"] = {
                "only": providers,
                "allow_fallbacks": True,
            }
        models[openrouter_slug(model_id, providers)] = ChatOpenAI(
            model=model_id,
            base_url=AgentSettings.openrouter_base_url,
            api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
            temperature=0,
            max_tokens=AgentSettings.openrouter_max_tokens,
            max_retries=AgentSettings.llm_max_retries,
            timeout=300,
            # Attribution headers: they name the run in the OpenRouter
            # dashboard and are otherwise inert.
            default_headers={
                "HTTP-Referer": "https://github.com/wri/project-zeno",
                "X-Title": "project-zeno",
            },
            extra_body=extra_body or None,
        )
    return models


# Model Registry for dynamic selection
MODEL_REGISTRY: dict[str, BaseChatModel] = {
    "sonnet": SONNET,
    "haiku": HAIKU,
    "gemini": GEMINI,
    "gemini-flash": GEMINI_FLASH,
    "gemini-flash-3.8": GEMINI_FLASH_38,
    "gemini-flash-lite": GEMINI_FLASH_LITE,
    # "gpt": GPT,
    **build_openrouter_models(),
}

# Available models list for frontend
AVAILABLE_MODELS = list(MODEL_REGISTRY.keys())


def get_model():
    """Get the configured model from environment or default to sonnet."""
    model_name = AgentSettings.model.lower()
    if model_name not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model: {model_name}. Available models: {AVAILABLE_MODELS}"
        )
    return MODEL_REGISTRY[model_name]


def get_small_model():
    """Get the configured small model from environment or default to haiku."""
    model_name = AgentSettings.small_model.lower()
    if model_name not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown small model: {model_name}. Available models: {AVAILABLE_MODELS}"
        )
    return MODEL_REGISTRY[model_name]


def get_fallback_models():
    """Get the configured fallback models from environment.

    Returns a list of BaseChatModel instances, filtering out the primary model.
    Returns empty list if FALLBACK_MODELS is empty.
    Raises ValueError if any model name is unknown.
    """
    raw = AgentSettings.fallback_models.strip()
    if not raw:
        return []
    primary = AgentSettings.model.lower()
    models = []
    for name in raw.split(","):
        name = name.strip().lower()
        if not name or name == primary:
            continue
        if name not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown fallback model: {name}. Available models: {AVAILABLE_MODELS}"
            )
        models.append(MODEL_REGISTRY[name])
    return models


# Base Model - dynamically selected from environment
MODEL = get_model()

# Small Model - dynamically selected from environment
SMALL_MODEL = get_small_model()

# Fallback models for resilience
FALLBACK_MODELS = get_fallback_models()
