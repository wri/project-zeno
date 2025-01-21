import uuid

from langgraph.types import Command

from zeno.agents.distalert.graph import graph as dist_alert


def test_distalert_agent():
    """
    This test just runs the agent without checking any output, it is intended
    to be used for debugging
    """
    config = {
        "configurable": {"thread_id": uuid.uuid4()},
    }
    query = "Provide data about disturbance alerts in Aveiro summarized by natural lands in 2023"
    stream = dist_alert.stream(
        {"messages": [query]},
        stream_mode="updates",
        subgraphs=False,
        config=config,
    )
    for chunk in stream:
        print(str(chunk)[:300], "\n")

    query = "Averio"
    stream = dist_alert.stream(
        Command(
            goto="dist_alert",
            update={
                "messages": [query],
            },
        ),
        stream_mode="updates",
        subgraphs=False,
        config=config,
    )
    for chunk in stream:
        print(str(chunk)[:300], "\n")
