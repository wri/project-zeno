from zeno.tools.contextlayer.context_layer_tool import context_layer_tool


def test_context_layer_tool_cereal():
    result = context_layer_tool.invoke(
        input={"question": "Summarize disturbance alerts by type of cereal"}
    )
    assert result == "ESA/WorldCereal/2021/MODELS/v100"

def test_context_layer_tool_null():
    result = context_layer_tool.invoke(
        input={"question": "Provide disturbances for Aveiro Portugal"}
    )
    assert result == ""
