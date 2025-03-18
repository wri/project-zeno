from zeno.agents.gfw_data_api import tool_query as tools
from dotenv import load_dotenv

load_dotenv()


def test_query_tool():
    result = tools.query_tool.invoke(
        input={
            "gadm_level": 1,
            "gadm_ids": [
                "BRA.1_1",
                "BRA.2_1",
                "BRA.3_1",
                "BRA.4_1",
                "BRA.5_1",
                "BRA.6_1",
                "BRA.7_1",
                "BRA.8_1",
                "BRA.9_1",
                "BRA.10_1",
                "BRA.12_1",
                "BRA.11_1",
                "BRA.13_1",
                "BRA.14_1",
                "BRA.15_1",
                "BRA.16_1",
                "BRA.17_1",
                "BRA.18_1",
                "BRA.19_1",
                "BRA.20_1",
                "BRA.21_1",
                "BRA.22_1",
                "BRA.23_1",
                "BRA.24_1",
                "BRA.25_1",
                "BRA.26_1",
                "BRA.27_1",
            ],
            "user_query": "total carbon sequestered by state",
        }
    )

    print(result)

    assert False
