import uuid
from importlib import import_module
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
import structlog
from sqlalchemy import select

from src.agent.tools.pick_aoi import pick_aoi
from src.api.data_models import WhitelistedUserOrm
from tests.conftest import async_session_maker

# Use session-scoped event loop to match conftest.py fixtures and avoid
# "Event loop is closed" errors when running with other test modules
pytestmark = pytest.mark.asyncio(loop_scope="session")


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


async def test_query_aoi_multiple_matches(structlog_context):
    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "Measure deforestation in Puri",
                "places": ["Puri"],
            },
            "id": str(uuid.uuid4()),
            "type": "tool_call",
        }
    )
    assert str(command.update.get("messages")[0].content).startswith(
        "I found multiple locations named 'Puri"
    )


async def test_query_aoi_multiple_sources(structlog_context):
    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "Compare states in Ecuador and Bolivia",
                "places": ["Ecuador", "Bolivia"],
                "subregion": "state",
            },
            "id": str(uuid.uuid4()),
            "type": "tool_call",
        }
    )
    aois = command.update.get("aoi_selection", {}).get("aois")
    assert len(aois) == 33
    assert sum("ECU" in aoi.get("src_id") for aoi in aois) == 24
    assert sum("BOL" in aoi.get("src_id") for aoi in aois) == 9


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
async def test_query_aoi(question, place, expected_aoi_id, structlog_context):
    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": question,
                "places": [place],
            },
            "id": str(uuid.uuid4()),
            "type": "tool_call",
        }
    )
    assert len(command.update.get("aoi_selection", {}).get("aois")) == 1
    assert (
        command.update.get("aoi_selection", {}).get("aois")[0].get("src_id")
        == expected_aoi_id
    )


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
                "args": {
                    "question": "Measure deforestation in My Custom Area",
                    "places": ["My Custom Area"],
                },
                "id": str(uuid.uuid4()),
                "type": "tool_call",
            }
        )

    assert (
        command.update.get("aoi_selection", {}).get("name") == "My custom area"
    )


async def test_pick_aoi_handles_empty_subregion_results(
    monkeypatch, structlog_context
):
    pick_aoi_module = import_module("src.agent.tools.pick_aoi.tool")

    async def fake_query_aoi_database(place_name: str, result_limit: int = 10):
        return pd.DataFrame(
            [
                {
                    "src_id": "USA.6_1",
                    "name": "Colorado, United States",
                    "subtype": "state-province",
                    "source": "gadm",
                }
            ]
        )

    async def fake_select_best_aoi(question, candidate_aois):
        return {
            "src_id": "USA.6_1",
            "name": "Colorado, United States",
            "subtype": "state-province",
            "source": "gadm",
        }

    async def fake_query_subregion_database(
        subregion_name: str, source: str, src_id: int
    ):
        return pd.DataFrame(columns=["name", "subtype", "src_id", "source"])

    monkeypatch.setattr(
        pick_aoi_module, "query_aoi_database", fake_query_aoi_database
    )
    monkeypatch.setattr(
        pick_aoi_module, "select_best_aoi", fake_select_best_aoi
    )
    monkeypatch.setattr(
        pick_aoi_module,
        "query_subregion_database",
        fake_query_subregion_database,
    )

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "How much land changed to short vegetation in protected areas in Colorado in the past decade?",
                "places": ["Colorado"],
                "subregion": "wdpa",
            },
            "id": str(uuid.uuid4()),
            "type": "tool_call",
        }
    )

    assert "aoi_selection" not in command.update
    assert str(command.update["messages"][0].content).startswith(
        "No matching AOIs were found for your request."
    )


MOCK_COUNTRIES = [
    {
        "name": "Brazil",
        "subtype": "country",
        "src_id": "BRA",
        "source": "gadm",
        "gadm_id": "BRA",
    },
    {
        "name": "Indonesia",
        "subtype": "country",
        "src_id": "IDN",
        "source": "gadm",
        "gadm_id": "IDN",
    },
    {
        "name": "Canada",
        "subtype": "country",
        "src_id": "CAN",
        "source": "gadm",
        "gadm_id": "CAN",
    },
]


async def test_global_query_with_country_subregion(
    monkeypatch, structlog_context
):
    """Global World + subregion='country' should return all countries within the global bbox."""
    global_queries_module = import_module(
        "src.agent.tools.pick_aoi.global_queries"
    )

    async def fake_query_all_countries():
        return pd.DataFrame(MOCK_COUNTRIES)

    monkeypatch.setattr(
        global_queries_module, "_query_all_countries", fake_query_all_countries
    )

    command = await pick_aoi.ainvoke(
        {
            "args": {
                "question": "Which countries have the most deforestation globally?",
                "places": ["Global World"],
                "subregion": "country",
            },
            "id": str(uuid.uuid4()),
            "type": "tool_call",
        }
    )

    aois = command.update.get("aoi_selection", {}).get("aois")
    assert aois is not None
    assert len(aois) == 3
    assert all(aoi["subtype"] == "country" for aoi in aois)


async def test_global_query_without_subregion_is_rejected(structlog_context):
    """Global places short-circuit before DB lookup; missing subregion must not call _query_all_countries."""
    with patch(
        "src.agent.tools.pick_aoi.global_queries._query_all_countries",
        new=AsyncMock(
            side_effect=AssertionError(
                "_query_all_countries must not run without subregion='country'"
            )
        ),
    ):
        command = await pick_aoi.ainvoke(
            {
                "args": {
                    "question": "What is the deforestation rate in the world?",
                    "places": ["Global World"],
                },
                "id": str(uuid.uuid4()),
                "type": "tool_call",
            }
        )

    assert "aoi_selection" not in command.update
    assert "subregion" in str(command.update["messages"][0].content).lower()
