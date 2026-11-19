import types
import typing
from typing import Optional

from dotenv import load_dotenv
from google.genai.errors import ServerError
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from src.agent.config import AgentSettings
from src.shared.text_sanitize import strip_control_chars_deep

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
    model="gemini-3.5-flash-lite",
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
    model="gemini-3.5-flash-lite",
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

    For model calls made from tools and API routes. ModelRetryMiddleware and
    ModelFallbackMiddleware (graph._build_middleware) cover only the agent's
    own calls, and the clients are built with LLM_MAX_RETRIES=0, so a model
    called directly from a tool gets its retries and fallbacks here.

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
    chain = primary.with_fallbacks(fallbacks) if fallbacks else primary
    return chain | _strip_control_chars_from(schema)


def _strip_control_chars_from(schema: type[BaseModel]) -> Runnable:
    """Strip control characters from every string in a structured reply.

    Gemini Flash sometimes puts a control character where an accented letter
    belongs (PZB-1243). Done once, after the fallbacks, so the reply is
    cleaned whichever model produced it.
    """

    def _strip(reply: BaseModel) -> BaseModel:
        return schema.model_validate(
            strip_control_chars_deep(reply.model_dump(), field=schema.__name__)
        )

    return RunnableLambda(_strip)


_JSON_KINDS = {
    str: "a string",
    int: "an integer",
    float: "a number",
    bool: "a boolean",
}
_JSON_ARRAY_ITEMS = {
    str: "strings",
    int: "integers",
    float: "numbers",
    bool: "booleans",
}


_UNIONS = (typing.Union, types.UnionType)


def json_reply_instruction(schema: type[BaseModel]) -> str:
    """The prompt line asking for a JSON reply with `schema`'s keys.

    Only flat schemas are supported: str, int, float and bool fields, and
    lists of them. Anything else raises TypeError, naming the field.
    """
    keys = [
        f'"{name}" ({_describe(name, field.annotation)})'
        for name, field in schema.model_fields.items()
    ]
    if len(keys) == 1:
        listed = f"this key: {keys[0]}"
    else:
        listed = f"these keys: {', '.join(keys[:-1])} and {keys[-1]}"
    return (
        "Reply with a single JSON object and nothing else, with exactly "
        f"{listed}. Do not wrap it in code fences."
    )


def _describe(name: str, annotation) -> str:
    """How the instruction describes one field's type."""
    if annotation in _JSON_KINDS:
        return _JSON_KINDS[annotation]
    if typing.get_origin(annotation) is list:
        (item,) = typing.get_args(annotation) or (None,)
        if item in _JSON_ARRAY_ITEMS:
            return f"an array of {_JSON_ARRAY_ITEMS[item]}"
    raise TypeError(
        f'Field "{name}" has type {_type_name(annotation)}, which '
        "json_reply_instruction cannot describe. Supported types are "
        f"{', '.join(_type_name(k) for k in _JSON_KINDS)}, and lists of them."
    )


def _type_name(annotation) -> str:
    """A short, readable name for a type: `_Place`, `list[_Place]`.

    Unions (note Optionals are Union[<type>, NoneType]) are written out as
    `<type> | <type>`, because Python names them differently depending
    on the version and on how they were written.
    """
    if annotation is type(None):
        return "None"
    origin = typing.get_origin(annotation)
    if origin is None:
        return getattr(annotation, "__qualname__", repr(annotation))
    args = [_type_name(a) for a in typing.get_args(annotation)]
    if origin in _UNIONS:
        return " | ".join(args)
    return f"{_type_name(origin)}[{', '.join(args)}]"
