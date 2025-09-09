import pytest

from src.tools.pull_data import pull_data

# All dataset and intersection combinations from OpenAPI spec
# http://analytics-416617519.us-east-1.elb.amazonaws.com/openapi.json
# as of 2025-08-06
ALL_DATASET_COMBINATIONS = [
    # Ecosystem disturbance alerts without intersection
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": None,
    },
    # Ecosystem disturbance alerts with driver intersection
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": "driver",
    },
    # Ecosystem disturbance alerts with natural_lands intersection
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": "natural_lands",
    },
    # Ecosystem disturbance alerts with grasslands intersection
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": "grasslands",
    },
    # Ecosystem disturbance alerts with land_cover intersection
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": "land_cover",
    },
    # Global land cover (no intersections available)
    {
        "dataset_id": 1,
        "dataset_name": "Global land cover",
        "context_layer": None,
    },
    # Grassland (no intersections available)
    {
        "dataset_id": 2,
        "dataset_name": "Grassland",
        "context_layer": None,
    },
    # Natural lands (no intersections available)
    {
        "dataset_id": 3,
        "dataset_name": "Natural lands",
        "context_layer": None,
    },
    # Tree cover loss without intersection
    {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "context_layer": None,
    },
    # Tree cover loss with driver intersection
    {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "context_layer": "driver",
    },
    # Tree cover loss with primary_forest intersection
    {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "context_layer": "primary_forest",
    },
    # Tree cover loss with ifl intersection
    {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "context_layer": "ifl",
    },
    # Tree cover gain without intersection
    {
        "dataset_id": 5,
        "dataset_name": "Tree cover gain",
        "context_layer": None,
    },
    # Tree cover gain with primary_forest intersection
    {
        "dataset_id": 5,
        "dataset_name": "Tree cover gain",
        "context_layer": "primary_forest",
    },
    # Tree cover gain with intact_forest_landscape intersection
    {
        "dataset_id": 5,
        "dataset_name": "Tree cover gain",
        "context_layer": "intact_forest_landscape",
    },
    # Forest greenhouse gas net flux without intersection
    {
        "dataset_id": 6,
        "dataset_name": "Forest greenhouse gas net flux",
        "context_layer": None,
    },
    # Forest greenhouse gas net flux with primary_forest intersection
    {
        "dataset_id": 6,
        "dataset_name": "Forest greenhouse gas net flux",
        "context_layer": "primary_forest",
    },
    # Forest greenhouse gas net flux with intact_forest_landscape intersection
    {
        "dataset_id": 6,
        "dataset_name": "Forest greenhouse gas net flux",
        "context_layer": "intact_forest_landscape",
    },
    # Tree cover without intersection
    {
        "dataset_id": 7,
        "dataset_name": "Tree cover",
        "context_layer": None,
    },
    # Tree cover with primary_forest intersection
    {
        "dataset_id": 7,
        "dataset_name": "Tree cover",
        "context_layer": "primary_forest",
    },
    # Tree cover with intact_forest_landscape intersection
    {
        "dataset_id": 7,
        "dataset_name": "Tree cover",
        "context_layer": "intact_forest_landscape",
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


@pytest.mark.asyncio
@pytest.mark.parametrize("aoi_data", TEST_AOIS)
@pytest.mark.parametrize("dataset", ALL_DATASET_COMBINATIONS)
async def test_pick_aoi_queries(aoi_data, dataset):
    print(f"Testing {dataset['dataset_name']} with {aoi_data['name']}")
    update = {
        "aoi": aoi_data,
        "subregion_aois": None,
        "subregion": None,
        "aoi_names": [aoi_data["name"]],
        "subtype": aoi_data["subtype"],
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "dataset_name": dataset["dataset_name"],
            "reason": "",
            "tile_url": "",
            "context_layer": dataset["context_layer"],
        },
        "aoi_options": [
            {
                "aoi": aoi_data,
                "subregion_aois": None,
                "subregion": None,
                "subtype": aoi_data["subtype"],
            }
        ],
    }

    command = await pull_data.ainvoke(
        {
            "query": f"find {dataset['dataset_name'].lower()} in {aoi_data['query_description']}",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "aoi_names": [update["aoi"]["name"]],
            "dataset_name": dataset["dataset_name"],
            "tool_call_id": f"test-call-id-{aoi_data['src_id']}-{dataset['dataset_id']}",
            "state": update,
        }
    )

    msg = command.update.get("messages", [None])[0]
    if msg and msg.content.startswith(
        "Failed to get completed result after polling for"
    ):
        assert False
    else:
        raw_data = command.update.get("raw_data", {})
        assert aoi_data["src_id"] in raw_data
        assert dataset["dataset_id"] in raw_data[aoi_data["src_id"]]
