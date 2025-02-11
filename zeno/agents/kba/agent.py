from langchain_anthropic import ChatAnthropic

from zeno.agents.kba.tool_kba_data import kba_data_tool
from zeno.agents.kba.tool_kba_insights import kba_insights_tool
from zeno.agents.kba.tool_kba_timeseries import kba_timeseries_tool

# haiku = ChatAnthropic(model="claude-3-5-haiku-latest", temperature=0)
sonnet = ChatAnthropic(model="claude-3-5-sonnet-latest", temperature=0)


tools = [kba_data_tool, kba_insights_tool, kba_timeseries_tool]
kba_agent = sonnet.bind_tools(tools)
