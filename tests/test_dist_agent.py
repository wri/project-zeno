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
            print(f"Messager is {key}")
            for key2, val2 in val.items():
                if key2 == "messages":
                    for msg in val.get("messages", []):
                        print(msg.content)
                        if hasattr(msg, "tool_calls"):
                            print(msg.tool_calls)
                        if hasattr(msg, "artifact"):
                            print(str(msg.artifact)[:500])
                else:
                    print(key2, val2)
                pass


test_distalert_agent()
