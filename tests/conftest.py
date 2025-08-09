"""Test configuration and fixtures."""
import os
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient
from collections.abc import AsyncGenerator
from sqlalchemy import text
from sqlalchemy import NullPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from src.api.data_models import Base, UserOrm, ThreadOrm
from src.api.app import app, get_async_session, fetch_user_from_rw_api
from src.api.schemas import UserModel

# Test database settings
if (os.getenv('TEST_DATABASE_URL')):
    TEST_DB_URL = os.getenv("TEST_DATABASE_URL")
else:
    TEST_DB_URL = f"{os.getenv('DATABASE_URL')}_test"
engine_test = create_async_engine(TEST_DB_URL, poolclass=NullPool)
Session = sessionmaker(bind=engine_test, expire_on_commit=False)
async_session_maker = sessionmaker(
    engine_test,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base.metadata.bind = engine_test


async def override_get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


app.dependency_overrides[get_async_session] = override_get_async_session


@pytest_asyncio.fixture(scope="session", autouse=True)
async def test_db():
    """Create test database and clear it after each test."""
    # Set up test database
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Clean databases
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="session")
async def client() -> AsyncClient:
    t = ASGITransport(app=app)
    async with AsyncClient(transport=t, base_url="http://test") as client:
        yield client


async def clear_tables():
    """Truncate all tables, except the 'users' table, after running each test.
    """
    async with async_session_maker() as session:
        for table in Base.metadata.sorted_tables:
            if table.name != "users":
                await session.execute(
                    text(f"TRUNCATE {table.name} RESTART IDENTITY CASCADE;"),
                )
        await session.commit()


@pytest_asyncio.fixture(autouse=True, scope="function")
async def test_db_session():
    yield engine_test
    await clear_tables()
    await engine_test.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def user() -> UserOrm:
    async with async_session_maker() as session:
        u = UserOrm(
            name="test-user-wri",
            id="test-user-wri",
            email="admin@wri.org",
        )
        session.add(u)
        await session.commit()
        return u


@pytest_asyncio.fixture(scope="session", autouse=True)
async def user_ds() -> UserOrm:
    async with async_session_maker() as session:
        u = UserOrm(
            name="test-user-ds",
            id="test-user-ds",
            email="admin@developmentseed.org",
        )
        session.add(u)
        await session.commit()
        return u


@pytest.fixture(scope="function")
def auth_override():
    original_dependency = None

    def _auth_override(user_id: str):
        nonlocal original_dependency
        # Store the original dependency if we haven't already
        if original_dependency is None:
            original_dependency = app.dependency_overrides.get(fetch_user_from_rw_api)
        app.dependency_overrides[fetch_user_from_rw_api] = lambda: UserModel.model_validate(
            {
                "id": user_id,
                "name": user_id,
                "email": "admin@wri.org",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
        )

    yield _auth_override
    if original_dependency is not None:
        app.dependency_overrides[fetch_user_from_rw_api] = original_dependency
    else:
        app.dependency_overrides.pop(fetch_user_from_rw_api, None)


@pytest_asyncio.fixture(scope="session")
async def thread_factory():
    """Create a thread fixture."""

    async def _thread(user_id: str):
        unique_id = str(uuid.uuid4())[:8]

        async with async_session_maker() as session:
            # Create test thread that belongs to the mocked user
            thread = ThreadOrm(
                id=f"test-thread-{unique_id}",
                user_id=user_id,  # Must match mocked user ID
                agent_id="test-agent",
                name="Test Thread",
            )
            session.add(thread)
            await session.commit()
            await session.refresh(thread)

            return thread

    return _thread
