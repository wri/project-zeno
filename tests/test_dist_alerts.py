
from zeno.tools.dist.dist_alerts_tool import dist_alerts_tool


def test_dist_alert_tool():

    natural_lands = "WRI/SBTN/naturalLands/v1/2020"
    features = ["PRT.6.2.5_1"]
    result = dist_alerts_tool.invoke(
        input={"features": features, "landcover": natural_lands, "threshold": 5}
    )

    assert len(result) == 1
    assert "PRT.6.2.5_1" in result
