from zeno.agents.gfw_data_api.tool_location import location_tool, relative_location_tool
from zeno.agents.gfw_data_api.tool_query import query_tool
from zeno.agents.gfw_data_api.models import haiku

# from zeno.agents.distalert.tool_location import location_tool
# from zeno.agents.distalert.tool_stac import stac_tool


tools_with_hil = [location_tool, query_tool]
tools_with_hil_names = {t.name for t in tools_with_hil}
tools = [relative_location_tool]

gfw_data_api_agent = haiku.bind_tools(tools + tools_with_hil)
