import os
from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

# TODO: combine the defintions for the OpenAI models
# TODO: ChatAnthropic doesn't have a generic "json" type output. We can instead create an output parser class,

MODELS_CONFIG = [
    {
        "required_env_var": "OLLAMA_BASE_URL",
        "model_id": "llama3.2",
        "model_name": "Ollama llama3.2",
        "constructor_class": ChatOllama,
        "json_mode": {"param_name": "format", "param_value": "json"},
        "additional_params": {
            "base_url": os.environ.get("OLLAMA_BASE_URL"),
        },
    },
    {
        "required_env_var": "OLLAMA_BASE_URL",
        "model_id": "qwen2.5:7b",
        "model_name": "Ollama Qwen2.5 (7 billion)",
        "constructor_class": ChatOllama,
        "json_mode": {"param_name": "format", "param_value": "json"},
        "additional_params": {
            # "base_url": os.environ.get("OLLAMA_BASE_URL"),
        },
    },
    {
        "required_env_var": "ANTHROPIC_API_KEY",
        "model_id": "claude-3-5-sonnet-latest",
        "model_name": "Anthropic claude3.5 sonnet",
        "constructor_class": ChatAnthropic,
        "additional_params": {},
    },
    {
        "required_env_var": "ANTHROPIC_API_KEY",
        "model_id": "claude-3-5-haiku-latest",
        "model_name": "Anthropic claude3.5 haiku",
        "constructor_class": ChatAnthropic,
        "additional_params": {},
    },
    {
        "required_env_var": "OPENAI_API_KEY",
        "model_id": "gpt-3.5-turbo",
        "model_name": "OpenAI GPT3.5 turbo",
        "constructor_class": ChatOpenAI,
        "json_mode": {
            "param_name": "response_format",
            "param_value": {"type": "json_object"},
        },
        "additional_params": {
            "max_tokens": None,
            "timeout": None,
            "max_retries": 2,
        },
    },
    {
        "required_env_var": "OPENAI_API_KEY",
        "model_id": "gpt-4o-mini",
        "model_name": "OpenAI GPT4.0 mini",
        "constructor_class": ChatOpenAI,
        "json_mode": {
            "param_name": "response_format",
            "param_value": {"type": "json_object"},
        },
        "additional_params": {
            "max_tokens": None,
            "timeout": None,
            "max_retries": 2,
        },
    },
]


class ModelFactory:
    def __init__(self):
        self.available_models = {
            model["model_id"]: model
            for model in MODELS_CONFIG
            # if model["required_env_var"] in os.environ
        }

    @lru_cache
    def get(self, model_id, json_mode=False):
        if not self.available_models.get(model_id):
            raise ValueError(
                f"Model {model_id} not avaialable. Available models: {self.available_models.keys()} (note: models are available if the required API key is set as an environment variable)"
            )
        model_config = self.available_models[model_id]
        params = model_config["additional_params"]

        if json_mode and not model_config.get("json_mode"):
            raise ValueError(
                f"Request model {model_id} does not support json mode"
            )

        if json_mode:
            params.update(
                {
                    model_config["json_mode"]["param_name"]: model_config[
                        "json_mode"
                    ]["param_value"]
                }
            )

        return model_config["constructor_class"](
            model=model_id, streaming=True, temperature=0, **params
        )
