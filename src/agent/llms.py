import os
import re

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from pydantic import BaseModel, ValidationError

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
    temperature=1.0,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    thinking_level="low",
    max_retries=AgentSettings.llm_max_retries,
    timeout=300,
)
GEMINI_FLASH = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    temperature=0.3,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=AgentSettings.llm_max_retries,
    thinking_level="low",
    timeout=300,
)
GEMINI_FLASH_LITE = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite-preview",
    temperature=0.3,
    max_tokens=None,  # max_tokens=None means no limit
    include_thoughts=False,
    max_retries=AgentSettings.llm_max_retries,
    thinking_level="low",
    timeout=300,
)
# OpenAI
# GPT = ChatOpenAI(
#     model="gpt-4o",
#     temperature=0,
#     max_tokens=None,  # max_tokens=None means no limit
# )

# Ollama Cloud
# Hosted inference at https://ollama.com authenticated with a bearer API key
# (OLLAMA_API_KEY). The same ChatOllama class also works against a local
# Ollama daemon by overriding base_url/OLLAMA_API_KEY in the environment.
_OLLAMA_CLOUD_KWARGS = dict(
    base_url="https://ollama.com",
    client_kwargs={
        "headers": {
            "Authorization": f"Bearer {os.environ.get('OLLAMA_API_KEY', '')}"
        }
    },
    # Note: Ollama Cloud rejects num_predict=-1 ("max_tokens must be positive"),
    # so leave it unset to use the model's default output length.
)
# General/small chat model: OpenAI open-weight MoE, native tool calling.
GPT_OSS = ChatOllama(
    model="gpt-oss:120b-cloud",
    temperature=0.3,
    reasoning="low",  # gpt-oss supports low/medium/high reasoning intensity
    **_OLLAMA_CLOUD_KWARGS,
)
# General/small model for tool-heavy subagents (geocoder, dataset selection,
# naming). Benchmarked as the most reliable accessible Ollama Cloud model on
# nested structured-output decisions.
NEMOTRON = ChatOllama(
    model="nemotron-3-super",
    temperature=0.3,
    **_OLLAMA_CLOUD_KWARGS,
)
# Code-specialized model used to drive the local code executor.
QWEN3_CODER = ChatOllama(
    model="qwen3-coder:480b-cloud",
    temperature=0.3,
    **_OLLAMA_CLOUD_KWARGS,
)

# Model Registry for dynamic selection
MODEL_REGISTRY = {
    "sonnet": SONNET,
    "haiku": HAIKU,
    "gemini": GEMINI,
    "gemini-flash": GEMINI_FLASH,
    "gemini-flash-lite": GEMINI_FLASH_LITE,
    "gpt-oss": GPT_OSS,
    "nemotron": NEMOTRON,
    "qwen3-coder": QWEN3_CODER,
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


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _as_messages(prompt_value):
    """Normalise a chain input (str / PromptValue / message list) to messages."""
    if isinstance(prompt_value, str):
        return [HumanMessage(content=prompt_value)]
    if hasattr(prompt_value, "to_messages"):
        return prompt_value.to_messages()
    return list(prompt_value)


def structured_output(model, schema: type[BaseModel]) -> Runnable:
    """Provider-agnostic structured output that tolerates weaker models.

    ``with_structured_output(method="function_calling")`` forces the tool call
    on Gemini/Anthropic, but Ollama models don't honour that forcing and often
    emit the JSON in the message *content* instead of as a tool call (and their
    schema-constrained ``format`` mode mangles nested objects). So we bind the
    schema as a forced tool and accept either path: parse the tool-call args if
    present, otherwise parse the JSON object out of the message content.

    Weaker models also drop required nested fields, so on a parse/validation
    failure we retry once, feeding the error back so the model can fill them in.

    Returns a Runnable, so it composes as ``PROMPT | structured_output(m, S)``.
    """
    bound = model.bind_tools([schema], tool_choice="any")

    def _parse(message) -> BaseModel:
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            return schema.model_validate(tool_calls[0]["args"])
        text = str(getattr(message, "text", "") or "")
        match = _JSON_OBJECT_RE.search(text)
        if match:
            return schema.model_validate_json(match.group(0))
        raise OutputParserException(
            f"No structured {schema.__name__} found in model output: "
            f"{text[:200]!r}"
        )

    async def _run(prompt_value) -> BaseModel:
        messages = _as_messages(prompt_value)
        message = await bound.ainvoke(messages)
        try:
            return _parse(message)
        except (ValidationError, OutputParserException) as err:
            # Weaker models often omit required fields on the first try; show
            # them the error and ask for a corrected, complete tool call.
            retry_messages = [
                *messages,
                AIMessage(content=str(getattr(message, "text", "") or "")),
                HumanMessage(
                    content=(
                        f"That did not match the {schema.__name__} schema: "
                        f"{err}. Reply again, calling the {schema.__name__} "
                        "tool with ALL required fields populated."
                    )
                ),
            ]
            return _parse(await bound.ainvoke(retry_messages))

    return RunnableLambda(_run)


# Base Model - dynamically selected from environment
MODEL = get_model()

# Small Model - dynamically selected from environment
SMALL_MODEL = get_small_model()

# Fallback models for resilience
FALLBACK_MODELS = get_fallback_models()
