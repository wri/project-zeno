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
    model="gemini-3-pro-preview",
    temperature=1.0,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=2,
    timeout=300,
)
GEMINI_FLASH = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    temperature=0.3,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=2,
    thinking_budget=0,
    timeout=300,
)
GEMINI_FLASH_LITE = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    temperature=0.3,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=2,
    thinking_budget=-1,
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


# Base Model - dynamically selected from environment
MODEL = get_model()

# Small Model - dynamically selected from environment
SMALL_MODEL = get_small_model()
