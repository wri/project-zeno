from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from src.utils.config import APISettings

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
    model="gemini-2.5-pro",
    temperature=0.0,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=2,
    thinking_budget=256,
)
GEMINI_FLASH = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.0,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=2,
    thinking_budget=0,
)

# OpenAI
GPT = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    max_tokens=None,  # max_tokens=None means no limit
)

# DEEPSEEK
QWEN3 = ChatOllama(
    model="qwen3:8b",
    temperature=0,
    max_tokens=None,  # max_tokens=None means no limit
)

# GPT-OSS
GPT_OSS = ChatOllama(
    model="gpt-oss:120b-cloud",
    temperature=0,
    max_tokens=None,  # max_tokens=None means no limit
)

# GLM
GLM = ChatOllama(
    model="glm-4.6:cloud",
    temperature=0,
    max_tokens=None,  # max_tokens=None means no limit
)

# Minimax
MINIMAX = ChatOllama(
    model="minimax-m2:cloud",
    temperature=0,
    max_tokens=None,  # max_tokens=None means no limit
)

# Model Registry for dynamic selection
MODEL_REGISTRY = {
    "sonnet": SONNET,
    "haiku": HAIKU,
    "gemini": GEMINI,
    "gemini-flash": GEMINI_FLASH,
    "gpt": GPT,
    "qwen3": QWEN3,
    "gpt-oss": GPT_OSS,
    "glm": GLM,
    "minimax": MINIMAX,
    # "groq": GROQ,
}

# Available models list for frontend
AVAILABLE_MODELS = list(MODEL_REGISTRY.keys())


def get_model():
    """Get the configured model from environment or default to sonnet."""
    model_name = APISettings.model.lower()
    if model_name not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown model: {model_name}. Available models: {AVAILABLE_MODELS}"
        )
    return MODEL_REGISTRY[model_name]


def get_small_model():
    """Get the configured small model from environment or default to haiku."""
    model_name = APISettings.small_model.lower()
    if model_name not in MODEL_REGISTRY:
        raise ValueError(
            f"Unknown small model: {model_name}. Available models: {AVAILABLE_MODELS}"
        )
    return MODEL_REGISTRY[model_name]


# Base Model - dynamically selected from environment
MODEL = get_model()

# Small Model - dynamically selected from environment
SMALL_MODEL = get_small_model()
