from zeno.tools.location.location_matcher import LocationMatcher


def test_location_matcher():
    matcher = LocationMatcher("/Users/tam/Downloads/gadm41_PRT.gpkg")
    # Test queries demonstrating priority order
    test_queries = {
        "lisboa": ["PRT.12.7.18_1", "PRT.12.7.49_1", "PRT.12.7.17_1"],
        "Lamego": ["PRT.20.5.11_1", "PRT.9.6.4_1", "PRT.20.5.9_1"],
        "Sao Joao": ["PRT.12.7.41_1", "PRT.12.7.45_1", "PRT.12.7.49_1"],
        "Castelo Branco": ["PRT.6.2.5_1", "PRT.6.2.7_1", "PRT.6.2.10_1"],
    }

    for query, expected in test_queries.items():
        matches = matcher.find_matches(query)
        assert matches == expected


def test_location_matcher_bbox():
    matcher = LocationMatcher("/Users/tam/Downloads/gadm41_PRT.gpkg")
    coords = (
        -28.759502410999914,
        38.517414093000184,
        -28.699558257999968,
        38.57793426600017,
    )
    matches = matcher.find_by_bbox(*coords)

    assert "PRT.2.4.2_1" in matches
    assert len(matches) == 5


def test_location_matcher_id():
    matcher = LocationMatcher("/Users/tam/Downloads/gadm41_PRT.gpkg")
    result = matcher.get_by_id("PRT.6.2.5_1")
    assert result["features"][0]["properties"]["GID_3"] == "PRT.6.2.5_1"
