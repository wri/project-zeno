import pytest
from experiments.gadm_utils import GadmLocation, parse_expected_output

# --- Passing test cases (GadmnLocations should be equal) ---
passing_cases = [
    ({"gadm_id": "CHE.9"}, {"gadm_id": "CHE-9"}),
    # this should pass, hyphen and periods allowed
    ({"gadm_id": "CHE.9.1_1"}, {"gadm_id": "CHE-9-1_1"}),

    # this test should pass even though names are different.
    ({"gadm_id": "CHE.9", "name": "Glarus Süd"}, {"gadm_id": "CHE-9", "name": "Glarus Sud"}),

    # this should pass, ignoring gadm level property right now
    ({"gadm_id": "GBR.1.83_1", "name": "Sheffield", "gadm_level": "1"}, {"gadm_id": "GBR-1-83_1", "name": "Sheffield", "gadm_level": "3"}),
]

# --- Failing test cases ---
failing_cases = [
    ({"gadm_id": "RUS"}, {"gadm_id": "IDN"}),
    ({"gadm_id": "CHE.9.1_1"}, {"gadm_id": "CHE-9"}),
    ({"gadm_id": "IDN.26.4_1"}, {"gadm_id": "IDN-26-4"}),
    ({"gadm_id": "ZWE.4.5_2"}, {"gadm_id": "ZWE.4.5"}),
    ({"gadm_id": "FRA.6.1_1"}, {"gadm_id": "FRA-6-1"}),
    ({"gadm_id": "ITA.10.10_1"}, {"gadm_id": "ITA.10.11_1"}),
]

@pytest.mark.parametrize("loc1_dict, loc2_dict", passing_cases)
def test_gadm_location_equal(loc1_dict, loc2_dict):
    loc1 = parse_expected_output([loc1_dict])[0]
    loc2 = parse_expected_output([loc2_dict])[0]
    assert loc1 == loc2

@pytest.mark.parametrize("loc1_dict, loc2_dict", failing_cases)
def test_gadm_location_not_equal(loc1_dict, loc2_dict):
    loc1 = parse_expected_output([loc1_dict])[0]
    loc2 = parse_expected_output([loc2_dict])[0]
    assert loc1 != loc2

