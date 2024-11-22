import os
from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI


MODELS_CONFIG = [
    {
        "required_env_var": "OLLAMA_BASE_URL",
        "model_id": "llama3.2",
        "model_name": "Ollama llama3.22",
        "constructor_class": ChatOllama,
        "additional_params": {
            "base_url": os.environ.get("OLLAMA_BASE_URL"),
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
        "required_env_var": "OPENAI_API_KEY",
        "model_id": "gpt-3.5-turbo",
        "model_name": "OpenAI GPT3.5 turbo",
        "constructor_class": ChatOpenAI,
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
            if model["required_env_var"] in os.environ
        }

    def get(self, model_id, json_mode=False):
        if not self.available_models.get(model_id):
            raise ValueError(
                f"Model {model_id} not avaialable. Available models: {self.available_models.keys()} (note: models are available if the required API key is set as an environment variable)"
            )
        params = self.available_models[model_id]["additional_params"]
        if json_mode:
            params["format"] = "json"
        return self.available_models[model_id]["constructor_class"](
            model=model_id, streaming=True, temperature=0, **params
        )
