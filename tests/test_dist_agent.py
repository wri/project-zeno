from zeno.agents.distalert.agent import graph
from zeno.agents.maingraph.utils.state import GraphState
from langchain_core.messages import ToolMessage, AIMessage

def test_distalert_agent():
    initial_state = GraphState(
        question="Provide data about disturbance alerts in Aveiro summarized by landcover"
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
        if isinstance(msg, ToolMessage):
            yield pack({msg.name, msg.content})
        elif isinstance(msg, AIMessage):
            yield pack

        for key, val in chunk.items():
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
