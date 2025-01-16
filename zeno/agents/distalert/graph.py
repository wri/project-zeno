from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from zeno.agents.distalert.agent import dist_alert_agent
from zeno.agents.zeno.state import ZenoState


def dist_alert_node(state: ZenoState) -> Command[Literal["zeno"]]:
    result = dist_alert_agent.invoke(state)
    return Command(
        update={
            "messages": [AIMessage(content=result["messages"][-1].content)]
        },
        goto="zeno",
    )
