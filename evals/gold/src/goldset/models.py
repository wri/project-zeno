from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

from goldset.judge_config import HAIKU_MODEL

load_dotenv()

# timeout is load-bearing: judge calls are synchronous, so an unbounded request
# can stall a worker indefinitely (in one upstream API incident, every worker
# froze at its next judge call). Bounded here, and run_test additionally runs
# evaluations off the loop thread.
HAIKU = ChatAnthropic(
    model=HAIKU_MODEL,
    temperature=0,
    max_tokens=8_192,
    timeout=60.0,
    max_retries=2,
)
