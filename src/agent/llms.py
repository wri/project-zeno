from typing import Optional

from dotenv import load_dotenv
from google.genai.errors import ServerError
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

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

# Model Registry for dynamic selection
MODEL_REGISTRY = {
    "sonnet": SONNET,
    "haiku": HAIKU,
    "gemini": GEMINI,
    "gemini-flash": GEMINI_FLASH,
    "gemini-flash-lite": GEMINI_FLASH_LITE,
    # "gpt": GPT,
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


def _fallbacks_for(primary: str, raw: str):
    """The registry models named in comma-separated `raw`, minus `primary`.

    Raises ValueError if any model name is unknown.
    """
    models = []
    for name in raw.split(","):
        name = name.strip().lower()
        if not name or name == primary.lower():
            continue
        if name not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown fallback model: {name}. Available models: {AVAILABLE_MODELS}"
            )
        models.append(MODEL_REGISTRY[name])
    return models


def get_fallback_models():
    """Get the configured fallback models from environment.

    Returns a list of BaseChatModel instances, filtering out the primary model.
    Returns empty list if FALLBACK_MODELS is empty.
    Raises ValueError if any model name is unknown.
    """
    return _fallbacks_for(AgentSettings.model, AgentSettings.fallback_models)


def get_small_fallback_models():
    """The models SMALL_MODEL calls fall back to, from SMALL_FALLBACK_MODELS,
    filtering out the small model itself."""
    return _fallbacks_for(
        AgentSettings.small_model, AgentSettings.small_fallback_models
    )


# Base Model - dynamically selected from environment
MODEL = get_model()

# Small Model - dynamically selected from environment
SMALL_MODEL = get_small_model()

# Fallback models for resilience
FALLBACK_MODELS = get_fallback_models()

SMALL_FALLBACK_MODELS = get_small_fallback_models()

# Retry policy for model calls made outside the agent loop. Gemini answers
# 5xx (most often 503 UNAVAILABLE, "high demand") when it is briefly
# overloaded, and a retry a second or two later usually goes through. Other
# errors are not retried: a 400 fails the same way twice, and a 429 is better
# served by another model's quota than by waiting on this one's.
TRANSIENT_ERRORS = (ServerError,)
RETRY_ATTEMPTS = 3
RETRY_WAIT = {"initial": 1.0, "max": 4.0, "exp_base": 2.0}


def resilient_structured_output(
    schema: type[BaseModel], model: Optional[BaseChatModel] = None
) -> Runnable:
    """`model.with_structured_output(schema)`, retried and with fallbacks.

    For model calls made from tools and API routes. The agent's own calls are
    retried and fall back through ModelRetryMiddleware and
    ModelFallbackMiddleware (graph._build_middleware), but a tool calling a
    model directly gets none of that, and the clients themselves do not retry
    (LLM_MAX_RETRIES is 0), so a single 503 used to fail the whole tool call.

    Each model is retried on TRANSIENT_ERRORS; when one still fails, for any
    reason, the next is tried. `model` defaults to SMALL_MODEL followed by
    SMALL_FALLBACK_MODELS; a model passed in is used alone.
    """
    models = (
        [model] if model is not None else [SMALL_MODEL, *SMALL_FALLBACK_MODELS]
    )
    primary, *fallbacks = [
        m.with_structured_output(schema).with_retry(
            retry_if_exception_type=TRANSIENT_ERRORS,
            exponential_jitter_params=RETRY_WAIT,
            stop_after_attempt=RETRY_ATTEMPTS,
        )
        for m in models
    ]
    return primary.with_fallbacks(fallbacks) if fallbacks else primary
