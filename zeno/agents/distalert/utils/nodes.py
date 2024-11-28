from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from zeno.agents.maingraph.models import ModelFactory
from zeno.tools.dist.context_layer_tool import context_layer_tool
from zeno.tools.dist.dist_alerts_tool import dist_alerts_tool
from zeno.tools.location.location_tool import location_tool

_ = load_dotenv(".env")

tools = [dist_alerts_tool, context_layer_tool, location_tool]

# model = ModelFactory().get("claude-3-5-sonnet-latest").bind_tools(tools)
# model = ModelFactory().get("qwen2.5:7b").bind_tools(tools)
# model = ModelFactory().get("gpt-3.5-turbo").bind_tools(tools)
model = ModelFactory().get("gpt-4o-mini").bind_tools(tools)


def assistant(state):
    sys_msg = SystemMessage(
        content="""You are a helpful assistant tasked with answering the user queries for vegetation disturbance, tree cover loss, or deforestation.
Never try to guess locations or alert data. Always rely on tools to answer queries, and otherwise refuse to answer queries.
Always check if a context layer is required. Check that using the  `context-layer-tool`.
Think through the solution step-by-step first and then execute.
Use the `location-tool` to get polygons of any region or place by name.
Use the `dist-alerts-tool` to get vegetation disturbance information, pass the context layer as input

"""
    )
    if not state["messages"]:
        state["messages"] = [HumanMessage(state["question"])]

    return {
        "messages": [model.invoke([sys_msg] + state["messages"])],
        "route": "distalert",
    }


tool_node = ToolNode(tools)
