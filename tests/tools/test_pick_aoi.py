import uuid

import pytest
import structlog
from sqlalchemy import select

from src.agent.tools.pick_aoi import (
    SUBREGION_LIMIT,
    SUBREGION_LIMIT_KBA,
    check_aoi_selection,
    pick_aoi,
)
from src.api.data_models import WhitelistedUserOrm
from tests.conftest import async_session_maker

# Use session-scoped event loop to match conftest.py fixtures and avoid
# "Event loop is closed" errors when running with other test modules
pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# Unit tests for check_aoi_selection (no DB, no LLM)
# ---------------------------------------------------------------------------


def _make_aois(source: str, n: int) -> list[dict]:
    return [
        {"source": source, "src_id": f"{source}_{i}", "name": f"Area {i}", "subtype": "state-province"}
        for i in range(n)
    ]


async def test_check_aoi_selection_gadm_within_limit():
    result = await check_aoi_selection(_make_aois("gadm", SUBREGION_LIMIT))
    assert result is None


async def test_check_aoi_selection_gadm_exceeds_limit():
    aois = _make_aois("gadm", SUBREGION_LIMIT + 1)
    result = await check_aoi_selection(aois)
    assert result is not None
    assert str(SUBREGION_LIMIT + 1) in result
    assert str(SUBREGION_LIMIT) in result


async def test_check_aoi_selection_kba_within_limit():
    result = await check_aoi_selection(_make_aois("kba", SUBREGION_LIMIT_KBA))
    assert result is None


async def test_check_aoi_selection_kba_exceeds_limit():
    aois = _make_aois("kba", SUBREGION_LIMIT_KBA + 1)
    result = await check_aoi_selection(aois)
    assert result is not None
    assert str(SUBREGION_LIMIT_KBA + 1) in result


async def test_check_aoi_selection_wdpa_exceeds_limit():
    aois = _make_aois("wdpa", SUBREGION_LIMIT_KBA + 1)
    result = await check_aoi_selection(aois)
    assert result is not None


async def test_check_aoi_selection_multiple_sources():
    aois = _make_aois("gadm", 1) + _make_aois("kba", 1)
    result = await check_aoi_selection(aois)
    assert result is not None
    assert "multiple sources" in result.lower()


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
