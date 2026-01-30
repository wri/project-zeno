import uuid

import pytest
import structlog
from sqlalchemy import select

from src.agent.tools.pull_data import pull_data
from src.api.app import app, fetch_user_from_rw_api
from src.api.data_models import WhitelistedUserOrm
from src.api.schemas import UserModel
from tests.conftest import async_session_maker

# Use module-scoped event loop for all async tests in this module
# This prevents the "Event loop is closed" error when Google's gRPC clients
# cache their event loop reference across parameterized tests
pytestmark = pytest.mark.asyncio(loop_scope="module")

# All dataset and intersection combinations from OpenAPI spec
# https://analytics.globalnaturewatch.org/openapi.json
# as of 2025-08-06
ALL_DATASET_COMBINATIONS = [
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": None,
    },
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": "driver",
    },
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": "natural_lands",
    },
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": "grasslands",
    },
    {
        "dataset_id": 0,
        "dataset_name": "Ecosystem disturbance alerts",
        "context_layer": "land_cover",
    },
    {
        "dataset_id": 1,
        "dataset_name": "Global land cover",
        "context_layer": None,
    },
    {
        "dataset_id": 1,
        "dataset_name": "Global land cover",
        "context_layer": None,
        "check_composition": True,
    },
    {
        "dataset_id": 2,
        "dataset_name": "Grassland",
        "context_layer": None,
    },
    {
        "dataset_id": 3,
        "dataset_name": "Natural lands",
        "context_layer": None,
    },
    {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "context_layer": None,
    },
    {
        "dataset_id": 4,
        "dataset_name": "Tree cover loss",
        "context_layer": "driver",
    },
    {
        "dataset_id": 5,
        "dataset_name": "Tree cover gain",
        "context_layer": None,
    },
    {
        "dataset_id": 6,
        "dataset_name": "Forest greenhouse gas net flux",
        "context_layer": None,
    },
    {
        "dataset_id": 7,
        "dataset_name": "Tree cover",
        "context_layer": None,
    },
    {
        "dataset_id": 8,
        "dataset_name": "Tree cover loss by driver",
        "context_layer": "driver",
    },
    {
        "dataset_id": 9,
        "dataset_name": "Deforestation (sLUC) Emission Factors by Agricultural Crop",
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
        "src_id": "CHE.6.3_1",
        "gadm_id": "CHE.6.3_1",
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
        "src_id": "MEX9713",
        "gadm_id": None,
        "aoi_type": "indigenous-and-community-land",
        "query_description": "Indigenous land",
    },
]


@pytest.mark.parametrize("aoi_data", TEST_AOIS)
@pytest.mark.parametrize("dataset", ALL_DATASET_COMBINATIONS)
async def test_pull_data_queries(aoi_data, dataset):
    print(f"Testing {dataset['dataset_name']} with {aoi_data['name']}")

    update = {
        "aoi_selection": {
            "name": aoi_data["name"],
            "aois": [aoi_data],
        },
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "dataset_name": dataset["dataset_name"],
            "reason": "",
            "tile_url": "",
            "context_layer": dataset["context_layer"],
        },
    }
    if dataset.get("check_composition"):
        query = f"find composition of {dataset['dataset_name'].lower()} in {aoi_data['query_description']}"
    else:
        query = f"find {dataset['dataset_name'].lower()} in {aoi_data['query_description']}"
    tool_call = {
        "type": "tool_call",
        "name": "pull_data",
        "id": f"test-call-id-{aoi_data['src_id']}-{dataset['dataset_id']}",
        "args": {
            "query": query,
            "start_date": "2024-01-01"
            if dataset["dataset_id"] != 8
            else "2024-01-01",
            "end_date": "2024-01-31"
            if dataset["dataset_id"] != 8
            else "2024-01-31",
            "aoi_names": [
                aoi["name"] for aoi in update["aoi_selection"]["aois"]
            ],
            "dataset_name": dataset["dataset_name"],
            "change_over_time_query": False,
            "tool_call_id": f"test-call-id-{aoi_data['src_id']}-{dataset['dataset_id']}",
            "state": update,
        },
    }
    command = await pull_data.ainvoke(tool_call)
    analytics_data = command.update.get("analytics_data", {})
    if dataset["dataset_id"] not in [5, 9] and aoi_data["src_id"] not in [
        "6072",
        "148322",
        "MEX9713",
    ]:
        assert len(analytics_data) == 1
        assert analytics_data[0]["source_url"].startswith("http")
        assert analytics_data[0]["aoi_names"] == [aoi_data["name"]]
    else:
        assert len(analytics_data) == 0


async def whitelist_test_user():
    """Add the test user email to the whitelist to bypass signup restrictions."""
    async with async_session_maker() as session:
        # Use a unique email for this test to avoid conflicts
        test_email = "test-custom-area@wri.org"

        # Check if user is already whitelisted
        stmt = select(WhitelistedUserOrm).where(
            WhitelistedUserOrm.email == test_email
        )
        result = await session.execute(stmt)
        if result.scalars().first():
            return  # Already whitelisted

        # Add to whitelist
        whitelisted_user = WhitelistedUserOrm(email=test_email)
        session.add(whitelisted_user)
        await session.commit()


async def test_pull_data_custom_area(auth_override, client, structlog_context):
    # Whitelist the test user to bypass signup restrictions
    await whitelist_test_user()

    def mock_auth():
        return UserModel.model_validate(
            {
                "id": "test-user-123",
                "name": "test-user-123",
                "email": "test-custom-area@wri.org",  # Use the whitelisted email
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

    # Apply the override

    app.dependency_overrides[fetch_user_from_rw_api] = mock_auth

    # list custom areas
    res = await client.get(
        "/api/custom_areas",
        headers={"Authorization": "Bearer abc123"},
    )

    assert res.status_code == 200

    # create a custom area
    create_response = await client.post(
        "/api/custom_areas",
        json={
            "name": "My custom area",
            "geometries": [
                {
                    "coordinates": [
                        [
                            [29.2263174, -1.641965],
                            [29.2263174, -1.665582],
                            [29.2301511, -1.665582],
                            [29.2301511, -1.641965],
                            [29.2263174, -1.641965],
                        ]
                    ],
                    "type": "Polygon",
                }
            ],
        },
        headers={"Authorization": "Bearer abc123"},
    )

    assert create_response.status_code == 200

    response_json = create_response.json()

    aoi_data = {
        "name": response_json["name"],
        "subtype": "custom-area",
        "src_id": response_json["id"],
        "gadm_id": None,
        "aoi_type": "custom-area",
        "query_description": response_json["name"],
    }
    update = {
        "aoi_selection": {
            "name": aoi_data["name"],
            "aois": [aoi_data],
        },
        "dataset": {
            "dataset_id": 1,
            "dataset_name": "Global land cover",
            "reason": "",
            "tile_url": "",
            "context_layer": None,
        },
    }
    query = f"find commodities in {aoi_data['query_description']}"
    # Ensure user_id is bound to structlog context for the pick_aoi call
    with structlog.contextvars.bound_contextvars(user_id="test-user-123"):
        tool_call = {
            "type": "tool_call",
            "name": "pull_data",
            "id": str(uuid.uuid4()),
            "args": {
                "query": query,
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "dataset_name": "Global land cover",
                "change_over_time_query": False,
                "state": update,
                "aoi_names": [aoi_data["name"]],
            },
        }

        command = await pull_data.ainvoke(tool_call)

    analytics_data = command.update.get("analytics_data", {})

    assert aoi_data["src_id"] == analytics_data[0]["data"]["aoi_id"][0]
    assert aoi_data["name"] == analytics_data[0]["data"]["name"][0]
    assert analytics_data[0]["data"]["land_cover_class_end"] == ["Built-up"]
