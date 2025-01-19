import datetime

from zeno.agents.distalert import tools


def test_dist_alert_tool():
    result = tools.dist_alerts_tool.invoke(
        input={
            "name": "BRA.13.369_2",
            "gadm_id": "BRA.13.369_2",
            "gadm_level": 2,
            "context_layer_name": "WRI/SBTN/naturalLands/v1/2020",
            "threshold": 8,
            "min_date": datetime.date(2021, 8, 12),
            "max_date": datetime.date(2024, 8, 12),
        }
    )

    assert len(result) == 7
    assert "natural short vegetation" in result


def test_dist_alert_tool_verified(monkeypatch):
    # Target location and small buffer size.
    lon = -54.180643732357765
    lat = -24.047038901203194
    epsilon = 0.0005
    # For this location, using GEE directly, disturbances were
    # marked as wildfire and latest disturbance was 2024-04-29,
    # and the context layer was class 10, Wet natural short vegetation.
    expected_natural_lands = "wet natural short vegetation"
    expected_vegstatus = 6
    expected_vegdate = datetime.datetime(2024, 4, 29)  # 1215
    expected_driver = "wildfire"

    def mockfunction(gadm_id, gadm_level):

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

        return tools.ee.FeatureCollection([tools.ee.Feature(mockfeature)])

    monkeypatch.setattr(tools, "get_features", mockfunction)

    result = tools.dist_alerts_tool.invoke(
        input={
            "name": "IND.26.12_1",
            "gadm_id": "IND.26.12_1",
            "gadm_level": 2,
            "context_layer_name": "distalert-drivers",
            "threshold": expected_vegstatus,
            "min_date": expected_vegdate,
            "max_date": expected_vegdate,
        }
    )
    # Change is wildfire
    assert list(result.keys()) == [expected_driver]

    # Test for date range
    result = tools.dist_alerts_tool.invoke(
        input={
            "name": "IND.26.12_1",
            "gadm_id": "IND.26.12_1",
            "gadm_level": 2,
            "context_layer_name": "distalert-drivers",
            "threshold": expected_vegstatus,
            "min_date": expected_vegdate + datetime.timedelta(days=1),
            "max_date": expected_vegdate + datetime.timedelta(days=1),
        }
    )
    # Date is out of range, no results
    assert result == {}

    # Test for threshold
    result = tools.dist_alerts_tool.invoke(
        input={
            "name": "IND.26.12_1",
            "gadm_id": "IND.26.12_1",
            "gadm_level": 2,
            "context_layer_name": "distalert-drivers",
            "threshold": expected_vegstatus + 1,
            "min_date": expected_vegdate,
            "max_date": expected_vegdate,
        }
    )
    # Threshold is out of range, no results
    assert result == {}

    # Test for context_layer_name type
    result = tools.dist_alerts_tool.invoke(
        input={
            "name": "IND.26.12_1",
            "gadm_id": "IND.26.12_1",
            "gadm_level": 2,
            "context_layer_name": "WRI/SBTN/naturalLands/v1/2020",
            "threshold": expected_vegstatus,
            "min_date": expected_vegdate,
            "max_date": expected_vegdate,
        }
    )
    # Context layer type is as expected
    assert list(result.keys()) == [expected_natural_lands]


def test_dist_alert_tool_buffer():
    result = tools.dist_alerts_tool.invoke(
        input={
            "name": "BRA.13.369_2",
            "gadm_id": "BRA.13.369_2",
            "gadm_level": 2,
            "context_layer_name": "WRI/SBTN/naturalLands/v1/2020",
            "threshold": 8,
            "min_date": datetime.date(2021, 8, 12),
            "max_date": datetime.date(2024, 8, 12),
        }
    )
    result_buffered = tools.dist_alerts_tool.invoke(
        input={
            "name": "BRA.13.369_2",
            "gadm_id": "BRA.13.369_2",
            "gadm_level": 2,
            "context_layer_name": "WRI/SBTN/naturalLands/v1/2020",
            "threshold": 8,
            "min_date": datetime.date(2021, 8, 12),
            "max_date": datetime.date(2024, 8, 12),
            "buffer_distance": 1000,
        }
    )
    assert (
        result["natural short vegetation"] < result_buffered["natural short vegetation"]
    )


def test_dist_alert_tool_no_context():
    result = tools.dist_alerts_tool.invoke(
        input={
            "name": "BRA.13.369_2",
            "gadm_id": "BRA.13.369_2",
            "gadm_level": 2,
            "context_layer_name": None,
            "threshold": 8,
            "min_date": datetime.date(2021, 8, 12),
            "max_date": datetime.date(2024, 8, 12),
        }
    )

    assert len(result) == 1
    assert "disturbances" in result
