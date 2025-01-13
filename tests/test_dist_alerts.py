import datetime

from zeno.tools.contextlayer.layers import layer_choices
from zeno.tools.distalert import dist_alerts_tool


def test_dist_alert_tool():

    features = ["BRA.13.369_2"]
    result = dist_alerts_tool.dist_alerts_tool.invoke(
        input={
            "features": features,
            "landcover": layer_choices[1]["dataset"],
            "threshold": 8,
            "min_date": datetime.date(2021, 8, 12),
            "max_date": datetime.date(2024, 8, 12),
        }
    )

    assert len(result) == 1
    assert "BRA.13.369_2" in result


def test_dist_alert_tool_no_landcover():

    features = ["IND.26.12_1"]
    result = dist_alerts_tool.dist_alerts_tool.invoke(
        input={
            "features": features,
            "landcover": None,
            "threshold": 5,
            "min_date": datetime.date(2021, 8, 12),
            "max_date": datetime.date(2024, 8, 12),
        }
    )

    assert len(result) == 1
    assert "IND.26.12_1" in result


def test_dist_alert_tool_verified(monkeypatch):

    lon = -54.180643732357765
    lat = -24.047038901203194
    epsilon = 0.0005
    # For this location, disturbances were marked as wildfire
    # and latest disturbance was 2024-04-29, and the landcover
    # was class 10, Wet natural short vegetation
    exppected_natural_lands = "Wet natural short vegetation"
    expected_vegstatus = 6
    expected_vegdate = datetime.datetime(2024, 4, 29)  # 1215
    expected_driver = "wildfire"

    def mockfunction(features):

        mockfeature = {
            "type": "Feature",
            "properties": {"GID_2": "IND.26.12_1"},
            "geometry": {
                "coordinates": [
                    [
                        [lon, lat],
                        [lon + epsilon, lat],
                        [lon + epsilon, lat + epsilon],
                        [lon, lat + epsilon],
                        [lon, lat],
                    ]
                ],
                "type": "Polygon",
            },
        }

        return dist_alerts_tool.ee.FeatureCollection(
            [dist_alerts_tool.ee.Feature(mockfeature)]
        )

    monkeypatch.setattr(dist_alerts_tool, "get_features", mockfunction)

    features = ["IND.26.12_1"]
    result = dist_alerts_tool.dist_alerts_tool.invoke(
        input={
            "features": features,
            "landcover": "distalert-drivers",
            "threshold": expected_vegstatus,
            "min_date": expected_vegdate,
            "max_date": expected_vegdate,
        }
    )
    # Change is wildfire
    assert list(result["IND.26.12_1"].keys()) == [expected_driver]

    # Test for date range
    features = ["IND.26.12_1"]
    result = dist_alerts_tool.dist_alerts_tool.invoke(
        input={
            "features": features,
            "landcover": "distalert-drivers",
            "threshold": expected_vegstatus,
            "min_date": expected_vegdate + datetime.timedelta(days=1),
            "max_date": expected_vegdate + datetime.timedelta(days=1),
        }
    )
    # Date is out of range, no results
    assert result["IND.26.12_1"] == {}

    # Test for threshold
    features = ["IND.26.12_1"]
    result = dist_alerts_tool.dist_alerts_tool.invoke(
        input={
            "features": features,
            "landcover": "distalert-drivers",
            "threshold": expected_vegstatus + 1,
            "min_date": expected_vegdate,
            "max_date": expected_vegdate,
        }
    )
    # Threshold is out of range, no results
    assert result["IND.26.12_1"] == {}

    # Test for landcover type
    features = ["IND.26.12_1"]
    result = dist_alerts_tool.dist_alerts_tool.invoke(
        input={
            "features": features,
            "landcover": "WRI/SBTN/naturalLands/v1/2020",
            "threshold": expected_vegstatus,
            "min_date": expected_vegdate,
            "max_date": expected_vegdate,
        }
    )
    # Threshold is out of range, no results
    assert list(result["IND.26.12_1"].keys()) == [exppected_natural_lands]
