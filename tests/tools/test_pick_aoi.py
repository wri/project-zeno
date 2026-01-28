import uuid

import pytest
import structlog
from sqlalchemy import select

from src.agent.tools.pick_aoi import pick_aoi
from src.api.data_models import UserOrm, WhitelistedUserOrm
from tests.conftest import AOI_MOCK_DATA, async_session_maker

# Use module-scoped event loop for all async tests in this module
# This prevents the "Event loop is closed" error when Google's gRPC clients
# cache their event loop reference across parameterized tests
pytestmark = pytest.mark.asyncio(loop_scope="module")


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


async def test_query_aoi_multiple_matches(
    mock_query_aoi_database, structlog_context
):
    """Test that multiple matching locations from different countries triggers disambiguation."""
    with mock_query_aoi_database(AOI_MOCK_DATA["puri_multiple_matches"]):
        command = await pick_aoi.ainvoke(
            {
                "args": {
                    "question": "Measure deforestation in Puri",
                    "place": "Puri",
                },
                "name": "pick_aoi",
                "type": "tool_call",
                "id": str(uuid.uuid4()),
            }
        )
    assert str(command.update.get("messages")[0].content).startswith(
        "I found multiple locations named 'Puri"
    )


@pytest.mark.parametrize(
    "question,place,expected_aoi_id,mock_data_key",
    [
        (
            "Analyze deforestation rates in the Para, Brazil",
            "Para, Brazil",
            "BRA.14_1",
            "para_brazil",
        ),
        (
            "Monitor land use changes in Indonesia",
            "Indonesia",
            "IDN",
            "indonesia",
        ),
        (
            "Track forest cover loss in Castelo Branco, Portugal",
            "Castelo Branco, Portugal",
            "PRT.6_1",
            "castelo_branco",
        ),
        (
            "Assess natual lands in Anjos, Lisbon",
            "Lisbon",
            "PRT.12.7.6_1",
            "lisbon",
        ),
        (
            "Assess natural lands in Resex Catua-Ipixuna",
            "Resex Catua-Ipixuna",
            "BRA79",
            "resex_catua_ipixuna",
        ),
        (
            "Assess natural lands in the Osceola, Research Natural Area, USA",
            "Osceola, Research Natural Area, USA",
            "555608530",
            "osceola_research_natural_area",
        ),
    ],
)
async def test_query_aoi(
    question,
    place,
    expected_aoi_id,
    mock_data_key,
    mock_query_aoi_database,
    structlog_context,
):
    """Test AOI selection with mocked database data captured from real queries."""
    with mock_query_aoi_database(AOI_MOCK_DATA[mock_data_key]):
        command = await pick_aoi.ainvoke(
            {
                "args": {
                    "question": question,
                    "place": place,
                },
                "name": "pick_aoi",
                "type": "tool_call",
                "id": str(uuid.uuid4()),
            }
        )

    assert command.update.get("aoi", {}).get("src_id") == expected_aoi_id


async def test_custom_area_selection(
    mock_query_aoi_database, auth_override, client, structlog_context
):
    """Test that custom areas are properly selected when queried."""
    # Whitelist the test user to bypass signup restrictions
    await whitelist_test_user()

    # Create the user in the database (required for foreign key constraint)
    async with async_session_maker() as session:
        # Check if user already exists
        stmt = select(UserOrm).where(UserOrm.id == "test-user-123")
        result = await session.execute(stmt)
        user = result.scalars().first()

        if not user:
            user = UserOrm(
                id="test-user-123",
                name="test-user-123",
                email="test-custom-area@wri.org",
            )
            session.add(user)
            await session.commit()

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

    # Mock the database query to return the custom area
    # This ensures the custom area is found and selected
    with mock_query_aoi_database(AOI_MOCK_DATA["my_custom_area"]):
        # Ensure user_id is bound to structlog context for the pick_aoi call
        with structlog.contextvars.bound_contextvars(user_id="test-user-123"):
            command = await pick_aoi.ainvoke(
                {
                    "args": {
                        "question": "Measure deforestation in My Custom Area",
                        "place": "My Custom Area",
                    },
                    "name": "pick_aoi",
                    "type": "tool_call",
                    "id": str(uuid.uuid4()),
                }
            )

    assert command.update.get("aoi", {}).get("name") == "My custom area"


async def test_pick_aoi_with_mocked_database(
    mock_query_aoi_database, structlog_context
):
    """Test pick_aoi with mocked query_aoi_database to avoid database dependency."""
    # Using the fixture with default mock data
    with mock_query_aoi_database() as mock_query:
        command = await pick_aoi.ainvoke(
            {
                "args": {
                    "question": "Analyze deforestation in Test Location",
                    "place": "Test Location",
                },
                "name": "pick_aoi",
                "type": "tool_call",
                "id": str(uuid.uuid4()),
            }
        )

        # Verify the mock was called with the expected arguments
        mock_query.assert_called_once_with("Test Location", 10)

        # Verify the result contains the mocked AOI
        assert command.update.get("aoi", {}).get("src_id") == "TEST.1_1"
        assert command.update.get("aoi", {}).get("name") == "Test Location"


async def test_pick_aoi_with_custom_mock_data(
    mock_query_aoi_database, structlog_context
):
    """Test pick_aoi with custom mock data."""
    import pandas as pd

    custom_df = pd.DataFrame(
        {
            "src_id": ["BRA.14_1"],
            "name": ["Para"],
            "subtype": ["state"],
            "source": ["gadm"],
            "similarity_score": [0.98],
        }
    )

    with mock_query_aoi_database(custom_df) as mock_query:
        command = await pick_aoi.ainvoke(
            {
                "args": {
                    "question": "Analyze deforestation in Para, Brazil",
                    "place": "Para, Brazil",
                },
                "name": "pick_aoi",
                "type": "tool_call",
                "id": str(uuid.uuid4()),
            }
        )

        mock_query.assert_called_once()
        assert command.update.get("aoi", {}).get("src_id") == "BRA.14_1"
