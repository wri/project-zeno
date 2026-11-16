import re
from functools import partial
from typing import Optional

from dotenv import load_dotenv
from google.genai.errors import ServerError
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ValidationError

from src.agent.config import AgentSettings
from src.shared.logging_config import get_logger

load_dotenv()

logger = get_logger(__name__)

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
    return primary.with_fallbacks(fallbacks) if fallbacks else primary


class StructuredOutputFormatError(ValueError):
    """The model's reply was not valid JSON of the requested shape."""


_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

_JSON_TYPES = {
    "string": ("a string", "strings"),
    "integer": ("an integer", "integers"),
    "number": ("a number", "numbers"),
    "boolean": ("a boolean", "booleans"),
}


def _json_type_phrase(schema: type[BaseModel], name: str, spec: dict) -> str:
    kind = spec.get("type")
    if kind in _JSON_TYPES:
        return _JSON_TYPES[kind][0]
    item = spec.get("items", {}).get("type")
    if kind == "array" and item in _JSON_TYPES:
        return f"an array of {_JSON_TYPES[item][1]}"
    raise TypeError(
        f"{schema.__name__}.{name}: json_reply_instruction handles flat "
        "schemas of strings, numbers, booleans and lists of them. Nested "
        "or optional fields need their own prompt wording, checked against "
        "the model first."
    )


def json_reply_instruction(schema: type[BaseModel]) -> str:
    """The prompt text that asks for a JSON object shaped like ``schema``.

    ``resilient_json_output`` sends no response schema (that is the point), so
    the keys have to be spelled out in the prompt. Pass the text in as a
    template variable (for example ``{reply_format}``) so its quotes never need
    escaping in a ``ChatPromptTemplate``.
    """
    properties = schema.model_json_schema().get("properties", {})
    if not properties:
        raise ValueError(f"{schema.__name__} has no fields to ask for")
    keys = [
        f'"{name}" ({_json_type_phrase(schema, name, spec)})'
        for name, spec in properties.items()
    ]
    listed = (
        keys[0] if len(keys) == 1 else f"{', '.join(keys[:-1])} and {keys[-1]}"
    )
    return (
        "Reply with a single JSON object and nothing else, with exactly "
        f"these keys: {listed}. Do not wrap it in code fences."
    )


def _reply_model(message) -> Optional[str]:
    """The model version Gemini reports on a reply, when it reports one."""
    metadata = getattr(message, "response_metadata", None) or {}
    return metadata.get("model_version") or metadata.get("model_name")


def parse_json_reply(schema: type[BaseModel], message) -> BaseModel:
    """Validate a model's reply as a ``schema`` object.

    Code fences around the JSON are tolerated. On failure, logs where and how
    the reply was wrong, never the reply itself (it can repeat user and place
    names), and raises ``StructuredOutputFormatError``.
    """
    text = message if isinstance(message, str) else str(message.text)
    try:
        return schema.model_validate_json(_CODE_FENCE.sub("", text.strip()))
    except ValidationError as exc:
        errors = [
            {
                "loc": ".".join(str(part) for part in error["loc"])
                or "(root)",
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        logger.warning(
            "structured_output_format_error",
            schema=schema.__name__,
            model=_reply_model(message),
            errors=errors,
            length=len(text),
        )
        raise StructuredOutputFormatError(
            f"{schema.__name__}: {len(errors)} validation error(s)"
        ) from exc


def _transient_retry() -> dict:
    # Read at call time, so tests (and a deploy-time override) can change them.
    return {
        "retry_if_exception_type": TRANSIENT_ERRORS,
        "exponential_jitter_params": RETRY_WAIT,
        "stop_after_attempt": RETRY_ATTEMPTS,
    }


def _json_output_for(
    model: BaseChatModel, schema: type[BaseModel]
) -> Runnable:
    if not isinstance(model, ChatGoogleGenerativeAI):
        # The JSON mime type is a Gemini parameter, and the fault it works
        # around is Gemini's. Other providers keep their own structured output.
        return model.with_structured_output(schema).with_retry(
            **_transient_retry()
        )
    reply = model.bind(response_mime_type="application/json").with_retry(
        **_transient_retry()
    )
    return (
        reply | RunnableLambda(partial(parse_json_reply, schema))
    ).with_retry(
        retry_if_exception_type=(StructuredOutputFormatError,),
        stop_after_attempt=2,
        wait_exponential_jitter=False,
    )


def _failure_type(exc: Exception) -> str:
    if isinstance(exc, StructuredOutputFormatError):
        return "format"
    if isinstance(exc, ServerError):
        return "server"
    return "other"


def _log_when_it_fails(chain: Runnable, schema: type[BaseModel]) -> Runnable:
    """Log one ``structured_output_failed`` event when ``chain`` gives up."""

    def log(exc: Exception) -> None:
        logger.error(
            "structured_output_failed",
            schema=schema.__name__,
            error_type=_failure_type(exc),
            error=type(exc).__name__,
        )

    def invoke(value, config: RunnableConfig):
        try:
            return chain.invoke(value, config)
        except Exception as exc:
            log(exc)
            raise

    async def ainvoke(value, config: RunnableConfig):
        try:
            return await chain.ainvoke(value, config)
        except Exception as exc:
            log(exc)
            raise

    return RunnableLambda(invoke, afunc=ainvoke, name="resilient_json_output")


def resilient_json_output(
    schema: type[BaseModel], model: Optional[BaseChatModel] = None
) -> Runnable:
    """Like `resilient_structured_output`, but without a response schema.

    Gemini Flash's schema-constrained decoding intermittently replaces accented
    letters with control characters ("Piau\\u0000"; PZB-1243). This asks for
    JSON through the JSON mime type instead, which did not show the fault, and
    validates the reply against ``schema`` here. Put ``json_reply_instruction``
    in the prompt so the model knows the shape.

    Each model keeps the same policy as `resilient_structured_output`: retried
    on TRANSIENT_ERRORS, and one malformed reply is retried too. When a model
    still fails, for any reason, the next is tried. `model` defaults to
    SMALL_MODEL followed by SMALL_FALLBACK_MODELS; a model passed in is used
    alone. A non-Gemini model keeps `with_structured_output`.

    When every model has failed, one ``structured_output_failed`` event is
    logged and the last error is raised.
    """
    models = (
        [model] if model is not None else [SMALL_MODEL, *SMALL_FALLBACK_MODELS]
    )
    primary, *fallbacks = [_json_output_for(m, schema) for m in models]
    chain = primary.with_fallbacks(fallbacks) if fallbacks else primary
    return _log_when_it_fails(chain, schema)
