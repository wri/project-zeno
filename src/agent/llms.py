from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from src.agent.config import AgentSettings

load_dotenv()

# Anthropic
SONNET = ChatAnthropic(
    model="claude-sonnet-4-20250514",
    temperature=0,
    max_tokens=64_000,  # Sonnet has a limit of max 64000 tokens
)
HAIKU = ChatAnthropic(
    model="claude-3-5-haiku-latest",
    temperature=0,
    max_tokens=8_192,  # Haiku has a limit of max 8192 tokens
)

# Google
GEMINI = ChatGoogleGenerativeAI(
    model="gemini-3.1-pro-preview",
    temperature=1.0,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    thinking_level="low",
    max_retries=AgentSettings.llm_max_retries,  # Retries handled by ModelRetryMiddleware
    timeout=300,
)
GEMINI_FLASH = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    temperature=0.3,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=AgentSettings.llm_max_retries,  # Retries handled by ModelRetryMiddleware
    thinking_level="low",
    timeout=300,
)
GEMINI_FLASH_LITE = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite-preview",
    temperature=0.3,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=AgentSettings.llm_max_retries,  # Retries handled by ModelRetryMiddleware
    thinking_level="low",
    timeout=300,
)
# OpenAI
GPT = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    max_tokens=None,  # max_tokens=None means no limit
)

# Model Registry for dynamic selection
MODEL_REGISTRY = {
    "sonnet": SONNET,
    "haiku": HAIKU,
    "gemini": GEMINI,
    "gemini-flash": GEMINI_FLASH,
    "gemini-flash-lite": GEMINI_FLASH_LITE,
    "gpt": GPT,
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
