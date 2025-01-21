import pytest

from zeno.agents.distalert.tool_location import location_tool

# Test data for level 1 locations
LEVEL_1_TEST_DATA = [
    ("California, USA", "USA.5_1"),
    ("Bavaria, Germany", "DEU.2_1"),
    ("Hokkaido, Japan", "JPN.12_1"),
    ("Punjab, India", "IND.28_1"),
    ("Queensland, Australia", "AUS.7_1"),
    ("Tuscany, Italy", "ITA.16_1"),
    ("Guangdong, China", "CHN.6_1"),
    ("Ontario, Canada", "CAN.9_1"),
    ("Tamil Nadu, India", "IND.31_1"),
]

# Test data for level 2 locations
LEVEL_2_TEST_DATA = [
    ("Manhattan, USA", "USA.33.32_1"),
    ("Munich, Germany", "DEU.2.54_1"),
    ("Liverpool, UK", "GBR.1.82_1"),
    ("Kyoto City, Japan", "JPN.22.13_1"),
    ("Barcelona, Spain", "ESP.6.1_1"),
    ("Oxford County, UK", "GBR.1.69_1"),
    ("Lyon, France", "FRA.1.11_1"),
    ("Bangalore Urban, India", "IND.16.3_1"),
    ("Milan, Italy", "ITA.10.8_1"),
    ("Vancouver, Canada", "CAN.2.14_1"),
    ("Catalonia, Spain", "ESP.6.2_1"),
]


@pytest.mark.parametrize("query,expected_id", LEVEL_1_TEST_DATA)
def test_level_1_locations(query, expected_id):
    """Test that level 1 locations return correct GADM IDs"""
    result = location_tool.invoke(input={"query": query})
    assert result == (expected_id, 1)


@pytest.mark.parametrize("query,expected_id", LEVEL_2_TEST_DATA)
def test_level_2_locations(query, expected_id):
    """Test that level 2 locations return correct GADM IDs"""
    result = location_tool.invoke(input={"query": query})
    assert result == (expected_id, 2)
