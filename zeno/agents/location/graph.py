from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from zeno.agents.location.agent import location_agent
from zeno.agents.maingraph.state import ZenoState


def location_node(state: ZenoState) -> Command[Literal["zeno"]]:
    result = location_agent.invoke(state)
    return Command(
        update={
            "messages": [AIMessage(content=result["messages"][-1].content)]
        },
        goto="zeno",
    )
