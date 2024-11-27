import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.config import RunnableConfig
from langchain_ollama import ChatOllama  # noqa

from agents.maingraph.models import ModelFactory

# llm_json_mode = ChatOllama(model="qwen2.5:7b", temperature=0, format="json")
llm_json_mode = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0)


def generate(state):
    pass


def maingraph(state, config: RunnableConfig):
    sys_msg = SystemMessage(
        content="""You are a helpful chatbot tasked with answering the user queries for WRI data API.
        You have 3 agents to choose from.
        Use the "layerfinder" agent if someone asks for available data
        Use the "docfinder" agent for general questions related to the World Resources Institute
        Use the "firealert" agent for questions related to forest fires
        Return JSON with single key, route, that is 'layerfinder', 'docfinder' or 'firealert' depending on the question."""
    )

    model_id = config["configurable"].get("model_id")
    model = ModelFactory().get(model_id, json_mode=True)

    response = model.invoke([sys_msg] + [HumanMessage(content=state["question"])])
    route = json.loads(response.content)["route"]
    if route == "layerfinder":
        print("---ROUTING-TO-LAYERFINDER---")
    elif route == "docfinder":
        print("---ROUTING-TO-DOCFINDER---")
    elif route == "firealert":
        print("---ROUTING-TO-FIREALERT---")
    else:
        raise ValueError(f"Route to {route} not found")

    return route
