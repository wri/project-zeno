
from zeno.tools.dist.dist_alerts_tool import dist_alerts_tool


def test_dist_alert_tool():
    # features = {
    #     "type": "FeatureCollection",
    #     "features": [
    #         {
    #             "type": "Feature",
    #             "geometry": {
    #                 "type": "Polygon",
    #                 "coordinates": [[
    #                     [-62.4, -16.5],
    #                     [-62.39999, -16.5],
    #                     [-62.39999, -16.49999],
    #                     [-62.4, -16.49999],
    #                     [-62.4, -16.5]
    #                 ]]
    #             },
    #             "properties": {},
    #         }
    #     ]
    # }

    # natural_lands = ee.Image("WRI/SBTN/naturalLands/v1/2020").select("classification")
    natural_lands = "WRI/SBTN/naturalLands/v1/2020"
    features = ["PRT.6.2.5_1"]
    result = dist_alerts_tool.invoke(
        input={"features": features, "landcover": natural_lands, "threshold": 5}
    )
    assert len(result) == 2
