from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv()

HAIKU = ChatAnthropic(
    model="claude-3-5-haiku-latest",
    temperature=0,
    max_tokens=8_192,  # Haiku has a limit of max 8192 tokens
)
