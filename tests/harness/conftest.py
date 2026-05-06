"""Override the project-wide DB-bound autouse fixtures so harness tests
run without Postgres. The harness MVP is fully in-memory."""

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def test_db():
    yield


@pytest_asyncio.fixture(autouse=True, scope="function")
async def test_db_session():
    yield


@pytest.fixture(autouse=True, scope="function")
def clear_auth_state():
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def _harness_no_db():
    yield
