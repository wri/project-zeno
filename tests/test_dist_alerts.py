from zeno.tools.contextlayer.layers import layer_choices
from zeno.tools.distalert.dist_alerts_tool import dist_alerts_tool


def test_dist_alert_tool():

    features = ["2323"]
    result = dist_alerts_tool.invoke(
        input={"features": features, "landcover": layer_choices[1]["dataset"], "threshold": 8}
    )

    assert len(result) == 1
    assert "AGO.1.3.4_1" in result

def test_dist_alert_tool_no_landcover():

    features = ["2323"]
    result = dist_alerts_tool.invoke(
        input={"features": features, "landcover": None, "threshold": 5}
    )

    assert len(result) == 1
    assert "AGO.1.3.4_1" in result
