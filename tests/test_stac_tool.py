import datetime

from zeno.tools.stac.stac_tool import stac_tool


def test_stac_tool():
    result = stac_tool.invoke(
        input={
            "bbox": (73.88168, 15.45949, 73.88268, 15.46049),
            "min_date": datetime.datetime(2024, 8, 1),
            "max_date": datetime.datetime(2024, 9, 1),
        }
    )
    assert len(result) == 7
    assert result[0] == "S2A_43PCT_20240831_0_L2A"
