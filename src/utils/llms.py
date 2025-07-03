from dotenv import load_dotenv

from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

load_dotenv()

SONNET = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)
HAIKU = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)
GPT = ChatOpenAI(model="gpt-4o", temperature=0)
PHI4 = ChatOllama(model="phi4-mini", temperature=0)