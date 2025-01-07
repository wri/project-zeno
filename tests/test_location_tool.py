from zeno.tools.location.location_tool import location_tool


def test_location_tool_name():
    fids = location_tool.invoke(
        input={"query": "Puri India"}
    )
    assert len(fids) == 5
    assert fids[0] == "IND.26.26.2_1"
