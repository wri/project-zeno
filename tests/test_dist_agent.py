from zeno.agents.distalert.agent import graph
from zeno.agents.maingraph.utils.state import GraphState


def test_distalert_agent():
    initial_state = GraphState(
        question="Provide data about disturbance alerts in Aveiro summarized by natural lands in 2023"
    )
    for namespace, chunk in graph.stream(
        initial_state, stream_mode="updates", subgraphs=True
    ):
        node_name = list(chunk.keys())[0]
        print(f"Namespace {namespace}")
        print(f"Node {node_name}")
        messages = chunk[node_name].get("messages")
        if not messages:
            continue
        msg = messages[0]
        if msg.name == "dist-alerts-tool":
            assert "Natural forests" in msg.content
        print(msg)
