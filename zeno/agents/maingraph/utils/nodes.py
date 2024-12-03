import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.config import RunnableConfig
from langchain_ollama import ChatOllama  # noqa

from zeno.agents.maingraph.models import ModelFactory

# llm_json_mode = ChatOllama(model="qwen2.5:7b", temperature=0, format="json")
llm_json_mode = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0)


def slasher(state):
    if state["question"].startswith("/"):
        route = state["question"].split(" ")[0].replace("/", "")
        print(f"---SLASH COMMAND {route} DETECTED---")
        if route not in ["layerfinder", "docfinder", "firealert", "distalert"]:
            raise ValueError(f"Slash-command {route} not valid")
        question_without_slash = state["question"].replace(f"/{route} ", "")
        return {"question": question_without_slash, "route": route}


def maingraph(state, config: RunnableConfig):
    sys_msg = SystemMessage(
        content="""You are a helpful chatbot tasked with answering the user queries about
        the World Reource Institute, and data it provides.
        You have several agents to choose from.
        Use the "layerfinder" agent if someone asks for what data is available in WRI
        Use the "docfinder" agent for general questions related to the World Resources Institute
        Use the "firealert" agent for questions related to forest fires
        Use the "distalert" agent for questions related to vegetation disturbances, tree cover loss, or similar
        Return JSON with single key, route, that is 'layerfinder', 'docfinder', 'firealert', or 'distalert' depending on the question."""
    )
    if state.get("route"):
        route = state["route"]
    else:
        model_id = config["configurable"].get("model_id", "gpt-4o-mini")
        model = ModelFactory().get(model_id, json_mode=True)

        response = model.invoke([sys_msg] + [HumanMessage(content=state["question"])])
        route = json.loads(response.content)["route"]

    if route == "layerfinder":
        print("---ROUTING-TO-LAYERFINDER---")
    elif route == "docfinder":
        print("---ROUTING-TO-DOCFINDER---")
    elif route == "firealert":
        print("---ROUTING-TO-FIREALERT---")
    elif route == "distalert":
        print("---ROUTING-TO-DISTALERT---")
    else:
        raise ValueError(f"Route to {route} not found")

    return route
