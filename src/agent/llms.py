import re
import types
import typing
from typing import Optional

from dotenv import load_dotenv
from google.genai.errors import ServerError
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ValidationError

from src.agent.config import AgentSettings
from src.shared.logging_config import get_logger
from src.shared.text_sanitize import strip_control_chars_deep

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
    `model` defaults to SMALL_MODEL followed by SMALL_FALLBACK_MODELS; a
    model passed in is used alone.
    """
    return _resilient_output(
        schema, model, lambda m: m.with_structured_output(schema)
    )


def _strip_control_chars_from(schema: type[BaseModel]) -> Runnable:
    """Strip control characters from every string in a structured reply.

    Gemini Flash sometimes puts a control character where an accented letter
    belongs (PZB-1243).
    """

    def _strip(reply: BaseModel) -> BaseModel:
        return _strip_and_validate(schema, reply)

    return RunnableLambda(_strip)


def _strip_and_validate(schema: type[BaseModel], reply: BaseModel):
    """`reply` with control characters stripped, validated again."""
    return schema.model_validate(
        strip_control_chars_deep(reply.model_dump(), field=schema.__name__)
    )


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


def _resilient_output(
    schema: type[BaseModel],
    model: Optional[BaseChatModel],
    build: typing.Callable[[BaseChatModel], Runnable],
) -> Runnable:
    """Retries, fallbacks and control-character stripping around `build`.

    `build(m)` turns one model into a pipeline that returns a `schema`
    instance. Each is retried on TRANSIENT_ERRORS; when one still fails, for
    any reason, the next model is tried. The reply is cleaned once at the
    end, whichever model produced it.
    """
    models = (
        [model] if model is not None else [SMALL_MODEL, *SMALL_FALLBACK_MODELS]
    )
    primary, *fallbacks = [
        build(m).with_retry(
            retry_if_exception_type=TRANSIENT_ERRORS,
            exponential_jitter_params=RETRY_WAIT,
            stop_after_attempt=RETRY_ATTEMPTS,
        )
        for m in models
    ]
    chain = primary.with_fallbacks(fallbacks) if fallbacks else primary
    return chain | _strip_control_chars_from(schema)


# Responses are sometimes encapsulated in code fences even though we request
# they not be
_CODE_FENCE = re.compile(r"\A\s*```(?:json)?\s*(.*?)\s*```\s*\Z", re.DOTALL)


class JsonReplyFormatError(ValueError):
    """A model's JSON reply could not be parsed or did not fit the schema.

    Says where and how it failed, as (location, error type) pairs, but never
    contains the reply text: replies can hold user data, and this error ends
    up in logs.
    """

    def __init__(
        self,
        schema_name: str,
        errors: list[tuple[str, str]],
        reply_length: int,
    ):
        self.schema_name = schema_name
        self.errors = errors
        self.reply_length = reply_length
        where = "; ".join(f"{loc}: {kind}" for loc, kind in errors)
        super().__init__(f"Reply does not fit {schema_name}: {where}")


def _location(loc: tuple) -> str:
    """A Pydantic error location as text: `follow_up_suggestions.0`."""
    return ".".join(str(part) for part in loc) or "(root)"


def parse_json_reply(schema: type[BaseModel], text: str) -> BaseModel:
    original = text
    fenced = _CODE_FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        return _strip_and_validate(schema, schema.model_validate_json(text))
    except ValidationError as error:
        raise JsonReplyFormatError(
            schema.__name__,
            [(_location(e["loc"]), e["type"]) for e in error.errors()],
            len(original),
        ) from error


def _parse_logging_format_errors(schema: type[BaseModel], reply) -> BaseModel:
    """`parse_json_reply` on a model's reply, logging any format error."""
    try:
        return parse_json_reply(schema, reply.text)
    except JsonReplyFormatError as error:
        logger.warning(
            "json_reply_format_error",
            schema=error.schema_name,
            model_version=reply.response_metadata.get("model_name"),
            errors=error.errors,
            reply_length=error.reply_length,
        )
        raise


def resilient_json_output(
    schema: type[BaseModel], model: Optional[BaseChatModel] = None
) -> Runnable:
    """Like `resilient_structured_output`, but Gemini is asked for JSON by
    mime type only, with no response schema, and the reply is parsed here.

    Schema-constrained decoding makes Gemini put control characters where
    accented letters belong (PZB-1243). The caller's prompt must spell out
    the keys: see `json_reply_instruction`. Other models keep
    `with_structured_output`.
    """

    def build(m: BaseChatModel) -> Runnable:
        if not isinstance(m, ChatGoogleGenerativeAI):
            return m.with_structured_output(schema)
        return m.bind(response_mime_type="application/json") | RunnableLambda(
            lambda reply: _parse_logging_format_errors(schema, reply)
        )

    return _resilient_output(schema, model, build)
