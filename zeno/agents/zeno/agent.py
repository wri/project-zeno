from zeno.agents.contextfinder.tools import context_layer_tool
from zeno.agents.distalert.tools import dist_alerts_tool
from zeno.agents.location.tools import location_tool
from zeno.agents.zeno.models import ModelFactory
from langchain_anthropic import ChatAnthropic

haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)

tools_with_hil = [location_tool]
tools_with_hil_names = {t.name for t in tools_with_hil}
tools = [dist_alerts_tool, context_layer_tool]

zeno_agent = haiku.bind_tools(tools + tools_with_hil)
