from langgraph.prebuilt import create_react_agent

from zeno.agents.distalert.prompts import DIST_ALERTS_PROMPT
from zeno.agents.distalert.tools import dist_alerts_tool
from zeno.agents.maingraph.models import ModelFactory
from zeno.agents.maingraph.state import ZenoState

model = ModelFactory().get("claude-3-5-haiku-latest")

dist_alert_agent = create_react_agent(
    model,
    tools=[dist_alerts_tool],
    state_schema=ZenoState,
    state_modifier=DIST_ALERTS_PROMPT,
)
