from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

load_dotenv()

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
GPT = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    max_tokens=None,  # max_tokens=None means no limit
)
PHI4 = ChatOllama(
    model="phi4-mini",
    temperature=0,
    num_predict=-1,  # num_predict is similar to max_tokens, -1 means no limit
)
SMOLLM2 = ChatOllama(
    model="smollm2",
    temperature=0,
    num_predict=-1,  # num_predict is similar to max_tokens, -1 means no limit
)
