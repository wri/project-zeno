from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

load_dotenv()

SONNET = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)
GEMINI = ChatGoogleGenerativeAI(
    model="gemini-2.5-pro",
    temperature=1.0,
    include_thoughts=True,
    max_retries=2,
    thinking_budget=-1,
)
GEMINI_FLASH = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=1.0,
    include_thoughts=True,
    max_retries=2,
    thinking_budget=-1,
)
HAIKU = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)
GPT = ChatOpenAI(model="gpt-4o", temperature=0)
PHI4 = ChatOllama(model="phi4-mini", temperature=0)
SMOLLM2 = ChatOllama(model="smollm2", temperature=0)
