from src.agent.middleware import format_session_block
from tests.unit.agent.imagery.factories import planet_imagery


def test_session_block_describes_planet_imagery_by_its_period():
    state = {"imagery": planet_imagery().model_dump(mode="json")}

    assert "Imagery: planet 2026-08-01 → 2026-08-31" in format_session_block(
        state
    )
