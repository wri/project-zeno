"""Unit tests for dashboard_writer's malformed-id contract.

The module's documented rule: malformed UUIDs are treated as not-found
(None/False), never an exception. These tests also pin down that the early
return happens *before* a database session is opened — the DB pool is patched
to fail loudly if touched.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.api.repositories import dashboard_writer
from src.api.repositories.dashboard_writer import _parse_uuid

BAD_IDS = ["not-a-uuid", "", None, 42, {"id": "x"}]


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Fail the test if any function under test opens a DB session."""
    pool = MagicMock(side_effect=AssertionError("must not open a DB session"))
    monkeypatch.setattr(dashboard_writer, "get_session_from_pool", pool)


class TestParseUuid:
    def test_uuid_string(self):
        value = uuid4()
        assert _parse_uuid(str(value)) == value

    def test_uuid_instance(self):
        value = uuid4()
        assert _parse_uuid(value) == value

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_malformed_is_none(self, bad):
        assert _parse_uuid(bad) is None


@pytest.mark.parametrize("bad", BAD_IDS)
class TestMalformedIdsAreNotFound:
    async def test_get_dashboard(self, bad):
        assert await dashboard_writer.get_dashboard(bad) is None

    async def test_add_widget(self, bad):
        assert (
            await dashboard_writer.add_widget(bad, widget_type="insight")
            is None
        )

    async def test_update_widget(self, bad):
        assert await dashboard_writer.update_widget(bad, position=1) is False

    async def test_remove_widget(self, bad):
        assert await dashboard_writer.remove_widget(bad) is False

    async def test_update_dashboard(self, bad):
        assert await dashboard_writer.update_dashboard(bad, name="x") is False

    async def test_delete_dashboard(self, bad):
        assert await dashboard_writer.delete_dashboard(bad) is False

    async def test_set_dashboard_public(self, bad):
        assert await dashboard_writer.set_dashboard_public(bad, True) is None


async def test_add_widget_malformed_insight_id_is_not_found():
    assert (
        await dashboard_writer.add_widget(
            str(uuid4()), widget_type="insight", insight_id="not-a-uuid"
        )
        is None
    )
