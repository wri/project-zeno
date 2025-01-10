from zeno.tools.location.location_tool import location_tool


def test_location_tool_name():
    fids = location_tool.invoke(input={"query": "Puri India", "gadm_level": 2})
    assert len(fids) == 3
    assert fids[0] == "IND.26.26_1"


def test_location_tool_name_level_1():
    fids = location_tool.invoke(input={"query": "Puri India", "gadm_level": 1})
    assert len(fids) == 3
    assert fids[0] == "IND.26_1"
