from zeno.agents.distalert.tool_context_layer import context_layer_tool


def test_context_layer_tool_cereal():
    msg = context_layer_tool.invoke(
        {
            "name": "context-layer-tool",
            "args": {"question": "Summarize disturbance alerts by natural lands"},
            "id": "42",
            "type": "tool_call",
        }
    )
    assert msg.content == "WRI/SBTN/naturalLands/v1/2020"
    assert "{z}/{x}/{y}" in msg.artifact["tms_url"]
