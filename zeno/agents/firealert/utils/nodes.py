from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from zeno.tools.charts.basic import barchart_tool
from zeno.tools.glad.weekly_alerts_tool import glad_weekly_alerts_tool
from zeno.tools.location.tool import location_tool

_ = load_dotenv(".env")

tools = [location_tool, glad_weekly_alerts_tool, barchart_tool]

# local_llm = "qwen2.5:7b"
# llm = ChatOllama(model=local_llm, temperature=0)
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0)
llm_with_tools = llm.bind_tools(tools)


def assistant(state):
    sys_msg = SystemMessage(
        content="""You are a helpful assistant tasked with answering the user queries for WRI data API.
Use the `location-tool` to get iso, adm1 & adm2 of any region or place.
Use the `glad-weekly-alerts-tool` to get forest fire information for a particular year. Think through the solution step-by-step first and then execute.
Use the `barchart_tool` to plot the data as a barchart & return as an image.

For eg: If the query is "Find forest fires in Milan for the year 2024"
Steps
1. Use the `location_tool` to get iso, adm1, adm2 for place `Milan` by passing `query=Milan`
2. Pass iso, adm1, adm2 along with year `2024` as args to `glad-weekly-alerts-tool` to get data about forest fire alerts.
3. Use the `barchart-tool` to create a barchart of the dataset
"""
    )
    if not state["messages"]:
        state["messages"] = [HumanMessage(state["question"])]
    return {
        "messages": [llm_with_tools.invoke([sys_msg] + state["messages"])],
        "route": "firealert",
    }


tool_node = ToolNode(tools)
