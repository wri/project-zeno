from langgraph.prebuilt import create_react_agent

from zeno.agents.location.prompts import LOCATION_PROMPT
from zeno.agents.location.tools import location_tool
from zeno.agents.maingraph.models import ModelFactory
from zeno.agents.maingraph.state import ZenoState

model = ModelFactory().get("claude-3-5-haiku-latest")

location_agent = create_react_agent(
    model,
    tools=[location_tool],
    state_schema=ZenoState,
    state_modifier=LOCATION_PROMPT,
)
