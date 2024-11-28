from zeno.agents.distalert.agent import graph
from zeno.agents.maingraph.utils.state import GraphState


def test_distalert_agent():
    initial_state = GraphState(
        question="Provide data about disturbance alerts in Aveiro summarized by landcover"
    )
    for level, data in graph.stream(
        initial_state, stream_mode="updates", subgraphs=True
    ):
        print(f"Level {level}")
        for key, val in data.items():
            print(f"Messager {key}")
            if "messages" in val:
                for msg in val.get("messages", []):
                    print(msg.content[:1000])
                    if hasattr(msg, "tool_calls"):
                        print(msg.tool_calls)
                    pass
