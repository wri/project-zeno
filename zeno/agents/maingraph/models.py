import os
from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI


class ModelFactory:
    def __init__(self, model_name: str):

        if model_name == "llama32":

            if not os.environ.get("OLLAMA_BASE_URL"):
                raise ValueError("OLLAMA_BASE_URL not set")
            self.llm = ChatOllama(
                model="llama3.2",
                base_url=os.environ["OLLAMA_BASE_URL"],
                temperature=0,
                streaming=True,
            )
            self.json_llm = ChatOllama(
                model="llama3.2",
                base_url=os.environ["OLLAMA_BASE_URL"],
                temperature=0,
                streaming=True,
                format="json",
            )

        if model_name == "sonnet35":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ValueError("ANTHROPIC_API_KEY not set")
            self.llm = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0)
            self.json_llm = ChatAnthropic(
                model="claude-3-5-sonnet-latest", temperature=0, format="json"
            )

        if model_name == "openai":
            if not os.environ.get("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API KEY not set")
            self.llm = ChatOpenAI(
                model="gpt-3.5-turbo",
                temperature=0,
                max_tokens=None,
                timeout=None,
                max_retries=2,
            )
            self.json_llm = ChatOpenAI(
                model="gpt-3.5-turbo",
                temperature=0,
                max_tokens=None,
                timeout=None,
                max_retries=2,
                format="json",
            )
        raise ValueError(f"Model name: {model_name} not supported")
