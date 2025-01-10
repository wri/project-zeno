from zeno.tools.contextlayer.context_layer_retriever_tool import (
    context_layer_tool,
)


def test_context_layer_tool_cereal():
    msg = context_layer_tool.invoke(
        {
            "name": "context-layer-tool",
            "args": {"question": "Summarize disturbance alerts by type of cereal"},
            "id": "42",
            "type": "tool_call",
        }
    )
    assert msg.content == "ESA/WorldCereal/2021/MODELS/v100"
    assert "{z}/{x}/{y}" in msg.artifact["tms_url"]
