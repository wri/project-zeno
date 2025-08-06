import pytest

from src.tools.pull_data import pull_data

# All dataset and intersection combinations from OpenAPI spec
# http://analytics-416617519.us-east-1.elb.amazonaws.com/openapi.json
# as of 2025-08-06
ALL_DATASET_COMBINATIONS = [
    # DIST-ALERT without intersection
    {
        "dataset_id": 14,
        "source": "LCL",
        "data_layer": "DIST-ALERT",
        "context_layer": None,
    },
    # DIST-ALERT with driver intersection
    {
        "dataset_id": 14,
        "source": "LCL",
        "data_layer": "DIST-ALERT",
        "context_layer": "driver",
    },
    # Tree Cover Loss without intersection
    {
        "dataset_id": 1,
        "source": "LCL",
        "data_layer": "Tree cover loss",
        "context_layer": None,
    },
    # Tree Cover Loss with driver intersection
    {
        "dataset_id": 1,
        "source": "GFW",
        "data_layer": "Tree cover loss",
        "context_layer": "driver",
    },
    # Land Cover Change (no intersections available)
    {
        "dataset_id": 2,
        "source": "LCL",
        "data_layer": "Land cover change",
        "context_layer": None,
    },
    # Natural Lands (no intersections available)
    {
        "dataset_id": 3,
        "source": "LCL",
        "data_layer": "Natural lands",
        "context_layer": None,
    },
    # Grasslands (no intersections available)
    {
        "dataset_id": 4,
        "source": "LCL",
        "data_layer": "Grasslands",
        "context_layer": None,
    },
]


TEST_AOIS = [
    {
        "name": "Brazil",
        "subtype": "country",
        "src_id": "BRA",
        "gadm_id": "BRA",
        "aoi_type": "country",
        "query_description": "Brazil country",
    },
    {
        "name": "Berne, Bern, Bern, Switzerland",
        "subtype": "municipality",
        "src_id": "CHE.6.3.1_1",
        "gadm_id": "CHE.6.3.1_1",
        "aoi_type": "municipality",
        "query_description": "municipality of Bern, Switzerland",
    },
    {
        "name": "Marungu highlands, Marungu highlands, COD",
        "subtype": "key-biodiversity-area",
        "src_id": "6072",
        "gadm_id": None,
        "aoi_type": "key-biodiversity-area",
        "query_description": "Marungu highlands",
    },
    {
        "name": "Protected area",
        "subtype": "protected-area",
        "src_id": "148322",
        "gadm_id": None,
        "aoi_type": "protected-area",
        "query_description": "Protected area",
    },
    {
        "name": "Indigenous land",
        "subtype": "indigenous-and-community-land",
        "src_id": "1918",
        "gadm_id": None,
        "aoi_type": "indigenous-and-community-land",
        "query_description": "Indigenous land",
    },
]


# Override database fixtures to avoid database connections for these unit tests
@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Override the global test_db fixture to avoid database connections."""
    pass


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    """Override the global test_db_session fixture to avoid database connections."""
    pass


@pytest.mark.parametrize("aoi_data", TEST_AOIS)
@pytest.mark.parametrize("dataset", ALL_DATASET_COMBINATIONS)
def test_pick_aoi_queries(aoi_data, dataset):
    update = {
        "aoi": aoi_data,
        "subregion_aois": None,
        "subregion": None,
        "aoi_name": aoi_data["name"],
        "subtype": aoi_data["subtype"],
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "source": dataset["source"],
            "data_layer": dataset["data_layer"],
            "tile_url": "https://tiles.globalforestwatch.org/umd_glad_dist_alerts/latest/dynamic/{z}/{x}/{y}.png?render_type=true_color",
            "context_layer": dataset["context_layer"],
        },
    }

    command = pull_data.invoke(
        {
            "query": f"find {dataset['data_layer'].lower()} in {aoi_data['query_description']}",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "aoi_name": update["aoi"]["name"],
            "dataset_name": dataset["data_layer"],
            "tool_call_id": f"test-call-id-{aoi_data['src_id']}-{dataset['dataset_id']}",
            "state": update,
        }
    )
    print(f"Testing {dataset['data_layer']} with {aoi_data['name']}")
    print(command.update)
    assert "raw_data" in command.update
    assert "value" in command.update["raw_data"]
    assert len(command.update["raw_data"]["value"]) > 0
