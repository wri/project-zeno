from langchain_anthropic import ChatAnthropic

from zeno.agents.distalert.tool_context_layer import context_layer_tool
from zeno.agents.distalert.tool_dist_alerts import dist_alerts_tool
from zeno.agents.distalert.tool_location import location_tool
from zeno.agents.distalert.tool_stac import stac_tool

haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)

tools_with_hil = [location_tool]
tools_with_hil_names = {t.name for t in tools_with_hil}
tools = [dist_alerts_tool, context_layer_tool, stac_tool]

dist_alert_agent = haiku.bind_tools(tools + tools_with_hil)
