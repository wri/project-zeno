import os
from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

models = {}

if os.environ.get("OLLAMA_BASE_URL"):

    models["llama32"] = ChatOllama(
        model="llama3.2",
        base_url=os.environ["OLLAMA_BASE_URL"],
        temperature=0,
        streaming=True,
    )
if os.environ.get("ANTHROPIC_API_KEY"):
    models["sonnet35"] = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0)

if os.environ.get("OPENAI_API_KEY"):
    models["openai"] = ChatOpenAI(
        model="gpt-3.5-turbo",
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )
