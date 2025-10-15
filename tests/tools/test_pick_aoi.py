import uuid

import pytest
import structlog
from sqlalchemy import select

from src.api.data_models import WhitelistedUserOrm
from src.tools.pick_aoi import pick_aoi
from tests.conftest import async_session_maker


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


@pytest.mark.asyncio
async def test_query_aoi_multiple_matches(structlog_context):
    command = await pick_aoi.ainvoke(
        {
            "question": "Measure deforestation in Puri",
            "place": "Puri",
            "tool_call_id": str(uuid.uuid4()),
        }
    )
    assert str(command.update.get("messages")[0].content).startswith(
        "I found multiple locations named 'Puri"
    )


@pytest.mark.parametrize(
    "question,place,expected_aoi_id",
    [
        (
            "Analyze deforestation rates in the Para, Brazil",
            "Para, Brazil",
            "BRA.14_1",
        ),
        ("Monitor land use changes in Indonesia", "Indonesia", "IDN"),
        (
            "Track forest cover loss in Castelo Branco, Portugal",
            "Castelo Branco, Portugal",
            "PRT.6_1",
        ),
        (
            "Assess natual lands in Anjos, Lisbon",
            "Lisbon",
            "PRT.12.7.6_1",
        ),
        (
            "Assess natural lands in Resex Catua-Ipixuna",
            "Resex Catua-Ipixuna",
            "BRA79",
        ),
        (
            "Assess natural lands in the Osceola, Research Natural Area, USA",
            "Osceola, Research Natural Area, USA",
            "555608530",
        ),
    ],
)
@pytest.mark.asyncio
async def test_query_aoi(question, place, expected_aoi_id, structlog_context):
    command = await pick_aoi.ainvoke(
        {
            "question": question,
            "place": place,
            "tool_call_id": str(uuid.uuid4()),
        }
    )

    assert command.update.get("aoi", {}).get("src_id") == expected_aoi_id


@pytest.mark.asyncio
async def test_custom_area_selection(auth_override, client, structlog_context):
    # Whitelist the test user to bypass signup restrictions
    await whitelist_test_user()

    # Override auth to use the whitelisted email
    from src.api.app import fetch_user_from_rw_api
    from src.api.schemas import UserModel

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
    from src.api.app import app

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

    # Ensure user_id is bound to structlog context for the pick_aoi call
    with structlog.contextvars.bound_contextvars(user_id="test-user-123"):
        command = await pick_aoi.ainvoke(
            {
                "question": "Measure deforestation in My Custom Area",
                "place": "My Custom Area",
                "tool_call_id": str(uuid.uuid4()),
            }
        )

    assert command.update.get("aoi", {}).get("name") == "My custom area"
