import json
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables.config import RunnableConfig
from agents.maingraph.models import ModelFactory


# llm_json_mode = ChatOllama(model="qwen2.5:7b", temperature=0, format="json")


def generate(state):
    pass


def maingraph(state, config: RunnableConfig):
    sys_msg = SystemMessage(
        content="""You are a helpful chatbot tasked with answering the user queries for WRI data API.
        You have two assistants that you can choose from.
        Use the "layerfinder" assistant if someone asks for available data
        Use the "docfinder" assistant for general questions related to the World Resources Institute
        Return JSON with single key, route, that is 'layerfinder' or 'docfinder' depending on the question."""
    )

    model_id = config["configurable"].get("model_id")
    model = ModelFactory().get(model_id, json_mode=True)

    response = model.invoke([sys_msg] + [HumanMessage(content=state["question"])])
    route = json.loads(response.content)["route"]
    if route == "layerfinder":
        print("---ROUTING-TO-LAYERFINDER---")
    elif route == "docfinder":
        print("---ROUTING-TO-DOCFINDER---")
    else:
        raise ValueError(f"Route to {route} not found")

    return route
