import random

from zeno.agents.location.agent import location_agent


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


def test_location_agent():
    import pdb

    # pick a random query each from LEVEL_1_TEST_DATA & LEVEL_2_TEST_DATA
    query_1 = random.choice(LEVEL_1_TEST_DATA)
    query_2 = random.choice(LEVEL_2_TEST_DATA)
    result_1 = location_agent.invoke(
        {"messages": [("user", "Find the location of " + query_1[0])]}
    )
    result_2 = location_agent.invoke(
        {"messages": [("user", "Find the location of " + query_2[0])]}
    )
    assert query_1[1] in result_1["messages"][-1].content[0]["text"]
    assert query_2[1] in result_2["messages"][-1].content[0]["text"]
