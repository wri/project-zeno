import json
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from zeno.agents.maingraph.models import ModelFactory
from zeno.tools.contextlayer.context_layer_retriever_tool import (
    context_layer_tool,
)
from zeno.tools.distalert.dist_alerts_tool import dist_alerts_tool
from zeno.tools.location.location_tool import location_tool

_ = load_dotenv(".env")

tools = [dist_alerts_tool, context_layer_tool, location_tool]

model = ModelFactory().get("claude-3-5-sonnet-latest").bind_tools(tools)
# model = ModelFactory().get("qwen2.5:7b").bind_tools(tools)
# model = ModelFactory().get("gpt-3.5-turbo").bind_tools(tools)
# model = ModelFactory().get("gpt-4o-mini").bind_tools(tools)


def assistant(state):
    sys_msg = SystemMessage(
        content="""You are a helpful assistant tasked with answering the user queries for vegetation disturbance, tree cover loss, or deforestation.
    Never try to guess locations or alert data. Always rely on tools to answer queries, and otherwise refuse to answer queries.

    Think through the solution step-by-step first and then execute.

    A context layer can be used to summarize vegetation disturbances by things like landcover or tree height categories.
    If such a context layer analysis is is requested, obtain the context layer using the `context-layer-tool`

    Use the `location-tool` to get polygons of any region or place by name. There are two levels, 1 is for
    state/province/regional analysis, and 2 is for smaller areas like municiaplities and counties. Use 2 level by default,
    and level 1 if someone asks for state/province/regional analysis.

    Use the `dist-alerts-tool` to get vegetation disturbance information, pass the context layer and the location as input.
    If the user asks for summarizing disturbance alerts by underlying cause or driver, do not use the `context-layer-tool`
    and pass `distalert-drivers` in the `landcover` argument like so `landcover="distalert-drivers"`. This will summarize
    the disturbance alerts by driver.
    """
    )

    if not state["messages"]:
        state["messages"] = [HumanMessage(state["question"])]

    return {
        "messages": [model.invoke([sys_msg] + state["messages"])],
        "route": "distalert",
    }

def human_review_location(state):
    last_msg = state["messages"][-1]

    if last_msg.name == "location-tool":
        options = json.loads(last_msg.content)

        human_input = interrupt({
            "question": "Pick the location you would like to query?",
            "options": options,
            "artifact": last_msg.artifact
        })

        action = human_input["action"]
        option = human_input["option"]
        artifact = {
            "type": "FeatureCollection",
            "features": [feature for idx,feature in enumerate(last_msg.artifact["features"]) if idx == option]
        }

        if action == "continue":
            return Command(goto="assistant")
        elif action == "update":
            last_msg.content = json.dumps([options[option]])
            last_msg.artifact = artifact
            return Command(goto="assistant")
        elif action == "feedback":
            pass
        else:
            raise ValueError(f"Invalid action: {action}")
    else:
        return Command(goto="assistant")

tool_node = ToolNode(tools)
