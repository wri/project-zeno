import uuid

import pytest
import pytest_asyncio

from src.tools.pick_aoi import pick_aoi
from src.utils.database import close_global_pool, initialize_global_pool


@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_db_pool():
    """Initialize global database pool for pick_aoi tests."""
    await initialize_global_pool()
    yield
    await close_global_pool()


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
