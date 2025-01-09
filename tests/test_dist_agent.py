import uuid

from langgraph.types import Command

from zeno.agents.distalert.agent import graph
from zeno.agents.maingraph.utils.state import GraphState


def test_distalert_agent():
    config = {
        "configurable": {"thread_id": uuid.uuid4()},
    }
    initial_state = GraphState(
        question="Provide data about disturbance alerts in Aveiro summarized by natural lands in 2023"
    )
    for namespace, chunk in graph.stream(
        initial_state, stream_mode="updates", subgraphs=True, config=config,
    ):
        node_name = list(chunk.keys())[0]
        print(f"Namespace {namespace}")
        print(f"Node {node_name}")

    assert len(chunk["__interrupt__"][0].value["options"]) == 3

    selected_index = 1

    for namespace, chunk in graph.stream(
        Command(resume={"action": "update", "option": selected_index}),
        stream_mode="updates",
        subgraphs=True,
        config=config,
    ):
        messages = chunk[node_name].get("messages")
        if not messages:
            continue
        msg = messages[0]
        print("HERE" * 5, msg.content)
        if msg.name == "dist-alerts-tool":
            assert "Natural forests" in msg.content
        print(msg)
