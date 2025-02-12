from langchain_anthropic import ChatAnthropic

from zeno.agents.distalert.tool_location import location_tool
from zeno.agents.kba.tool_kba_data import kba_data_tool
from zeno.agents.kba.tool_kba_insights import kba_insights_tool
from zeno.agents.kba.tool_kba_timeseries import kba_timeseries_tool

haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)
# sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0)

tools_with_hil = [location_tool]
tools_with_hil_names = {t.name for t in tools_with_hil}
tools = [kba_data_tool, kba_insights_tool, kba_timeseries_tool]
kba_agent = haiku.bind_tools(tools + tools_with_hil)
