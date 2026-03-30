import pytest_asyncio


@pytest_asyncio.fixture(scope="session", autouse=True)
async def test_db():
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_db_session():
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_db_pool():
    yield
