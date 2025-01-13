import datetime
import uuid

from zeno.agents.distalert.agent import graph
from zeno.agents.maingraph.utils.state import GraphState


def test_distalert_agent_level_2():
    config = {
        "configurable": {"thread_id": uuid.uuid4()},
    }
    initial_state = GraphState(
        question="Provide data about disturbance alerts in Aveiro in 2023 summarized by natural lands"
    )
    for _, chunk in graph.stream(
        initial_state,
        stream_mode="updates",
        subgraphs=True,
        config=config,
    ):
        if "assistant" in chunk:
            for msg in chunk["assistant"]["messages"]:
                for call in msg.tool_calls:
                    print(call["name"])
                    if call["name"] == "location-tool":
                        assert call["args"]["gadm_level"] == 2
                        assert call["args"]["query"] == "Aveiro"
                    if call["name"] == "dist-alerts-tool":
                        assert call["args"]["min_date"] == "2023-01-01"
                        assert call["args"]["max_date"] == "2023-12-31"

        if "tools" in chunk:
            for msg in chunk["tools"]["messages"]:
                if msg.name == "context-layer-tool":
                    assert "WRI/SBTN/naturalLands/v1" in msg.content


def test_distalert_agent_level_1():
    config = {
        "configurable": {"thread_id": uuid.uuid4()},
    }
    initial_state = GraphState(
        question="Provide data about disturbance alerts in Florida summarized by natural lands in 2023"
    )
    for _, chunk in graph.stream(
        initial_state,
        stream_mode="updates",
        subgraphs=True,
        config=config,
    ):
        if "assistant" in chunk:
            if chunk["assistant"]["messages"][0].tool_calls:
                call = chunk["assistant"]["messages"][0].tool_calls[0]
                if call["name"] == "location-tool":
                    assert call["args"]["gadm_level"] == 1
                    assert call["args"]["query"] == "Florida"
