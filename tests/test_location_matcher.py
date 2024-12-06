from zeno.tools.location.location_matcher import LocationMatcher


def test_location_matcher():
    matcher = LocationMatcher("data/gadm_410_small.gpkg")
    # Test queries demonstrating priority order
    test_queries = {
        "lisboa portugal": ["PRT.12.7.52_1"],
        "Liisboa portugal": ["PRT.6.2.5_1"],
        "Lisbon portugal": ["PRT.6.2.5_1"],
        "Lamego viseu portugal": ["PRT.20.5.11_1"],
        "Sao Joao Porto": ["PRT.12.7.41_1"],
        "Bern Switzerland": ["PRT.6.2.5_1"],
    }

    for query, expected in test_queries.items():
        matches = matcher.find_matches(query)
        print(query, matches.name, matches.gadmid)
        # assert list(matches.gadmid) == expected


def test_location_matcher_bbox():
    matcher = LocationMatcher("data/gadm_410_small.gpkg")
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
    matcher = LocationMatcher("data/gadm_410_small.gpkg")
    result = matcher.get_by_id("PRT.6.2.5_1")
    assert result["features"][0]["properties"]["gadmid"] == "PRT.6.2.5_1"
