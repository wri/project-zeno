"""Test configuration and fixtures."""

import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
import pytest_asyncio
import structlog
from httpx import ASGITransport, AsyncClient
from sqlalchemy import NullPool, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.app import app, fetch_user_from_rw_api
from src.api.data_models import Base, ThreadOrm, UserOrm, UserType
from src.api.schemas import UserModel
from src.shared.database import (
    close_global_pool,
    get_session_from_pool_dependency,
    initialize_global_pool,
)

# Test database settings
if os.getenv("TEST_DATABASE_URL"):
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


async def override_get_session_from_pool_dependency() -> (
    AsyncGenerator[AsyncSession, None]
):
    async with async_session_maker() as session:
        yield session


app.dependency_overrides[get_session_from_pool_dependency] = (
    override_get_session_from_pool_dependency
)


# Mock replay_chat function for tests to avoid checkpointer table dependencies
async def mock_replay_chat(thread_id):
    """Mock replay_chat that returns empty conversation history for tests."""

    def pack(data):
        import json

        return json.dumps(data) + "\n"

    # Return minimal conversation history for tests
    yield pack(
        {
            "node": "agent",
            "timestamp": "2025-01-01T00:00:00Z",
            "update": '{"messages": [{"type": "human", "content": "Test message"}]}',
        }
    )


# Apply the mock globally for all tests
patcher = patch("src.api.app.replay_chat", mock_replay_chat)
patcher.start()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def test_db():
    """Create test database and clear it after each test."""
    # Set up test database
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Clean up
    patcher.stop()  # Stop the replay_chat mock
    # Clean databases
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="session")
async def client() -> AsyncClient:
    t = ASGITransport(app=app)
    async with AsyncClient(transport=t, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def anonymous_client() -> AsyncClient:
    """Client configured for anonymous users with required NextJS headers."""
    t = ASGITransport(app=app)

    # Default headers for anonymous requests
    headers = {
        "X-API-KEY": "test-nextjs-api-key",  # Matches .env NEXTJS_API_KEY
        "X-ZENO-FORWARDED-FOR": "192.168.1.1",  # Test IP address
        "Authorization": "Bearer noauth:test-session-123",  # Anonymous session
    }

    async with AsyncClient(
        transport=t, base_url="http://test", headers=headers
    ) as client:
        yield client


async def clear_tables():
    """Truncate all tables after running each test."""
    async with async_session_maker() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(
                text(f"TRUNCATE {table.name} RESTART IDENTITY CASCADE;"),
            )
        await session.commit()


@pytest_asyncio.fixture(autouse=True, scope="function")
async def test_db_session():
    yield engine_test
    await clear_tables()
    await engine_test.dispose()


@pytest.fixture(autouse=True, scope="function")
def clear_auth_state():
    """Ensure auth state is cleared between tests."""
    yield
    # Clean up any auth overrides after each test
    app.dependency_overrides.pop(fetch_user_from_rw_api, None)


@pytest_asyncio.fixture(scope="function")
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


@pytest_asyncio.fixture(scope="function")
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
    # Store the original dependency before any changes
    original_dependency = app.dependency_overrides.get(fetch_user_from_rw_api)

    def _auth_override(user_id: str):
        nonlocal original_dependency
        # Store the original dependency if we haven't already
        if original_dependency is None:
            original_dependency = app.dependency_overrides.get(
                fetch_user_from_rw_api
            )
        app.dependency_overrides[fetch_user_from_rw_api] = (
            lambda: UserModel.model_validate(
                {
                    "id": user_id,
                    "name": user_id,
                    "email": "admin@wri.org",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                }
            )
        )

    yield _auth_override

    # Always restore to the original state
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
            # First, ensure the user exists (create if not exists)
            stmt = select(UserOrm).filter_by(id=user_id)
            result = await session.execute(stmt)
            user = result.scalars().first()

            if not user:
                # Create the user if it doesn't exist
                user = UserOrm(
                    id=user_id, name=user_id, email=f"{user_id}@example.com"
                )
                session.add(user)
                await session.commit()

            # Create test thread that belongs to the user
            thread = ThreadOrm(
                id=f"test-thread-{unique_id}",
                user_id=user_id,  # Must match mocked user ID
                agent_id="test-agent",
                name="Test Thread",
                is_public=False,  # Default to private
            )
            session.add(thread)
            await session.commit()
            await session.refresh(thread)

            return thread

    return _thread


@pytest.fixture(scope="function")
def structlog_context():
    """Provide structlog context with test user ID for all tests."""
    with structlog.contextvars.bound_contextvars(user_id="test-user-123"):
        yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_db_pool():
    """Initialize global database pool for pick_aoi tests."""
    await initialize_global_pool()
    yield
    await close_global_pool()


@pytest_asyncio.fixture(scope="function")
async def admin_user_factory():
    """Create admin user fixture."""

    async def _admin_user(email: str):
        async with async_session_maker() as session:
            # Create admin user
            admin_user = UserOrm(
                id=f"admin-{email.split('@')[0]}",
                name=f"Admin {email.split('@')[0]}",
                email=email,
                user_type=UserType.ADMIN.value,
            )
            session.add(admin_user)
            await session.commit()
            await session.refresh(admin_user)
            return admin_user

    return _admin_user


# =============================================================================
# AOI Database Mock Fixtures - Real data captured from database queries
# =============================================================================


@pytest.fixture(scope="function")
def mock_query_aoi_database():
    """
    Fixture to mock query_aoi_database for tests that don't need a real database.

    Usage:
        def test_something(mock_query_aoi_database):
            # With default mock data (single result)
            with mock_query_aoi_database() as mock:
                ...

            # With custom mock data
            custom_df = pd.DataFrame({
                "src_id": ["CUSTOM.1"],
                "name": ["Custom Location"],
                "subtype": ["country"],
                "source": ["gadm"],
                "similarity_score": [0.99],
            })
            with mock_query_aoi_database(custom_df) as mock:
                ...
    """

    @contextmanager
    def _mock_query_aoi_database(return_value: pd.DataFrame | None = None):
        if return_value is None:
            # Default mock: single matching result
            return_value = pd.DataFrame(
                {
                    "src_id": ["TEST.1_1"],
                    "name": ["Test Location"],
                    "subtype": ["district"],
                    "source": ["gadm"],
                    "similarity_score": [0.95],
                }
            )

        with patch(
            "src.agent.tools.pick_aoi.query_aoi_database",
            new_callable=AsyncMock,
            return_value=return_value,
        ) as mock:
            yield mock

    return _mock_query_aoi_database


# Real database query results captured for each test case
AOI_MOCK_DATA = {
    # test_query_aoi_multiple_matches - "Puri" returns multiple matches from different countries
    "puri_multiple_matches": pd.DataFrame(
        {
            "src_id": [
                "AGO.17.11.1_1",
                "AGO.17.11_1",
                "IND.26.26.2_1",
                "IND.26.26_1",
                "EST.10.9.19_1",
                "45579",
                "MEX4778",
            ],
            "name": [
                "Puri, Puri, Uíge, Angola",
                "Puri, Uíge, Angola",
                "Puri, Puri, Odisha, India",
                "Puri, Odisha, India",
                "Puuri, Põlva, Põlva, Estonia",
                "Purcari - Etulia, Purcari - Etulia, MDA",
                "Purisima, Ejido, MEX",
            ],
            "subtype": [
                "municipality",
                "district-county",
                "municipality",
                "district-county",
                "municipality",
                "key-biodiversity-area",
                "indigenous-and-community-land",
            ],
            "source": [
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "kba",
                "landmark",
            ],
            "similarity_score": [
                0.29411765933036804,
                0.29411765933036804,
                0.2777777910232544,
                0.2777777910232544,
                0.20000000298023224,
                0.20000000298023224,
                0.20000000298023224,
            ],
        }
    ),
    # test_query_aoi - "Para, Brazil"
    "para_brazil": pd.DataFrame(
        {
            "src_id": [
                "BRA.16_1",
                "BRA.14_1",
                "BRA.15_1",
                "BRA.15.12_2",
                "BRA",
                "BRA.15.133_2",
                "BRA.16.266_2",
                "BRA.14.144_2",
                "BRA.16.183_2",
                "BRA.15.84_2",
            ],
            "name": [
                "Paraná, Brazil",
                "Pará, Brazil",
                "Paraíba, Brazil",
                "Arara, Paraíba, Brazil",
                "Brazil",
                "Parari, Paraíba, Brazil",
                "Piên, Paraná, Brazil",
                "Xinguara, Pará, Brazil",
                "Jussara, Paraná, Brazil",
                "Ibiara, Paraíba, Brazil",
            ],
            "subtype": [
                "state-province",
                "state-province",
                "state-province",
                "district-county",
                "country",
                "district-county",
                "district-county",
                "district-county",
                "district-county",
                "district-county",
            ],
            "source": [
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
            ],
            "similarity_score": [
                0.7333333492279053,
                0.7142857313156128,
                0.6875,
                0.6315789222717285,
                0.5833333134651184,
                0.5789473652839661,
                0.5789473652839661,
                0.5714285969734192,
                0.5714285969734192,
                0.5714285969734192,
            ],
        }
    ),
    # test_query_aoi - "Indonesia"
    "indonesia": pd.DataFrame(
        {
            "src_id": [
                "IDN",
                "IDN.2_1",
                "IDN.24_1",
                "IDN.1_1",
                "IDN.23_1",
                "IDN.8_1",
                "IDN.8.3_1",
                "IDN.19_1",
                "IDN.4_1",
                "IDN.17_1",
            ],
            "name": [
                "Indonesia",
                "Bali, Indonesia",
                "Riau, Indonesia",
                "Aceh, Indonesia",
                "Papua, Indonesia",
                "Jambi, Indonesia",
                "Jambi, Jambi, Indonesia",
                "Maluku, Indonesia",
                "Banten, Indonesia",
                "Lampung, Indonesia",
            ],
            "subtype": [
                "country",
                "state-province",
                "state-province",
                "state-province",
                "state-province",
                "state-province",
                "district-county",
                "state-province",
                "state-province",
                "state-province",
            ],
            "source": [
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
            ],
            "similarity_score": [
                1.0,
                0.6666666865348816,
                0.6666666865348816,
                0.6666666865348816,
                0.625,
                0.625,
                0.625,
                0.5882353186607361,
                0.5882353186607361,
                0.5555555820465088,
            ],
        }
    ),
    # test_query_aoi - "Castelo Branco, Portugal"
    "castelo_branco": pd.DataFrame(
        {
            "src_id": [
                "PRT.6.2.5_1",
                "PRT.6.2_1",
                "PRT.6_1",
                "PRT.6.2.15_1",
                "PRT.6.2.4_1",
                "PRT.6.2.13_1",
                "PRT.6.9.3_1",
                "PRT.6.9.12_1",
                "PRT.6.9_1",
                "PRT.6.4_1",
            ],
            "name": [
                "Castelo Branco, Castelo Branco, Castelo Branco, Portugal",
                "Castelo Branco, Castelo Branco, Portugal",
                "Castelo Branco, Portugal",
                "Mata, Castelo Branco, Castelo Branco, Portugal",
                "Cafede, Castelo Branco, Castelo Branco, Portugal",
                "Lousa, Castelo Branco, Castelo Branco, Portugal",
                "Penamacor, Castelo Branco, Portugal",
                "Vale da Senhora da Póvoa, Penamacor, Castelo Branco, Portugal",
                "Penamacor, Castelo Branco, Portugal",
                "Fundão, Castelo Branco, Portugal",
            ],
            "subtype": [
                "municipality",
                "district-county",
                "state-province",
                "municipality",
                "municipality",
                "municipality",
                "municipality",
                "municipality",
                "district-county",
                "district-county",
            ],
            "source": [
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
            ],
            "similarity_score": [
                1.0,
                1.0,
                1.0,
                0.8275862336158752,
                0.8275862336158752,
                0.800000011920929,
                0.800000011920929,
                0.800000011920929,
                0.800000011920929,
                0.7741935253143311,
            ],
        }
    ),
    # test_query_aoi - "Lisbon" (for Anjos, Lisbon)
    "lisbon": pd.DataFrame(
        {
            "src_id": [
                "PRT.12.7_1",
                "PRT.12_1",
                "555654757",
                "PRT.12.7.52_1",
                "PRT.12.7.17_1",
                "PRT.12.7.24_1",
                "PRT.12.7.1_1",
                "PRT.12.7.6_1",
                "PRT.12.7.7_1",
                "PRT.12.7.16_1",
            ],
            "name": [
                "Lisboa, Lisboa, Portugal",
                "Lisboa, Portugal",
                "Lisbon, Forest Preserve, USA",
                "Sé, Lisboa, Lisboa, Portugal",
                "Lapa, Lisboa, Lisboa, Portugal",
                "Pena, Lisboa, Lisboa, Portugal",
                "Ajuda, Lisboa, Lisboa, Portugal",
                "Anjos, Lisboa, Lisboa, Portugal",
                "Beato, Lisboa, Lisboa, Portugal",
                "Graça, Lisboa, Lisboa, Portugal",
            ],
            "subtype": [
                "district-county",
                "state-province",
                "protected-area",
                "municipality",
                "municipality",
                "municipality",
                "municipality",
                "municipality",
                "municipality",
                "municipality",
            ],
            "source": [
                "gadm",
                "gadm",
                "wdpa",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
                "gadm",
            ],
            "similarity_score": [
                0.2777777910232544,
                0.2777777910232544,
                0.26923078298568726,
                0.2380952388048172,
                0.22727273404598236,
                0.22727273404598236,
                0.2083333283662796,
                0.2083333283662796,
                0.2083333283662796,
                0.2083333283662796,
            ],
        }
    ),
    # test_query_aoi - "Resex Catua-Ipixuna"
    "resex_catua_ipixuna": pd.DataFrame(
        {
            "src_id": [
                "BRA79",
                "352135",
                "BRA.14.56_2",
                "BRA.4.27_2",
                "33865",
                "CAN1095",
                "BRA.14.78_2",
                "BRA1495",
                "CAN2260",
                "126121",
            ],
            "name": [
                "Resex Catuá-Ipixuna, Reserva Extrativista, BRA",
                "Reserva Extrativista Catuá-Ipixuna, Reserva Extrativista, BRA",
                "Ipixuna do Pará, Pará, Brazil",
                "Ipixuna, Amazonas, Brazil",
                "Ipixuna, Terra Indígena, BRA",
                "Cacouna Indian Reserve No. 22, Indian Reserve, CAN",
                "Itupiranga, Pará, Brazil",
                "Resex do Baixo Juruá, Reserva Extrativista, BRA",
                "Canoe Lake No. 165, Indian Reserve, CAN",
                "Reserva Extrativista do Baixo Juruá, Reserva Extrativista, BRA",
            ],
            "subtype": [
                "indigenous-and-community-land",
                "protected-area",
                "district-county",
                "district-county",
                "protected-area",
                "indigenous-and-community-land",
                "district-county",
                "indigenous-and-community-land",
                "indigenous-and-community-land",
                "protected-area",
            ],
            "source": [
                "landmark",
                "wdpa",
                "gadm",
                "gadm",
                "wdpa",
                "landmark",
                "gadm",
                "landmark",
                "landmark",
                "wdpa",
            ],
            "similarity_score": [
                0.41860464215278625,
                0.3720930218696594,
                0.22857142984867096,
                0.2222222238779068,
                0.2222222238779068,
                0.2195121943950653,
                0.2162162214517593,
                0.2162162214517593,
                0.2162162214517593,
                0.2162162214517593,
            ],
        }
    ),
    # test_query_aoi - "Osceola, Research Natural Area, USA"
    "osceola_research_natural_area": pd.DataFrame(
        {
            "src_id": [
                "555608530",
                "555672701",
                "11115245",
                "555671421",
                "555610722",
                "11111360",
                "368228",
                "11115258",
                "369380",
                "11111384",
            ],
            "name": [
                "Osceola, Research Natural Area, USA",
                "Research, Natural Area, USA",
                "Ruth, Research Natural Area, USA",
                "No Name, Research Natural Area, USA",
                "Tiak, Research Natural Area, USA",
                "Bagby, Research Natural Area, USA",
                "Cathedral, Research Natural Area, USA",
                "Sam's, Research Natural Area, USA",
                "Fern, Research Natural Area, USA",
                "Boardman, Research Natural Area, USA",
            ],
            "subtype": [
                "protected-area",
                "protected-area",
                "protected-area",
                "protected-area",
                "protected-area",
                "protected-area",
                "protected-area",
                "protected-area",
                "protected-area",
                "protected-area",
            ],
            "source": [
                "wdpa",
                "wdpa",
                "wdpa",
                "wdpa",
                "wdpa",
                "wdpa",
                "wdpa",
                "wdpa",
                "wdpa",
                "wdpa",
            ],
            "similarity_score": [
                1.0,
                0.7647058963775635,
                0.6842105388641357,
                0.6666666865348816,
                0.6666666865348816,
                0.6499999761581421,
                0.6499999761581421,
                0.6499999761581421,
                0.6499999761581421,
                0.6499999761581421,
            ],
        }
    ),
    # test_custom_area_selection - "My Custom Area" (custom area should be returned first)
    "my_custom_area": pd.DataFrame(
        {
            "src_id": ["custom-area-uuid"],
            "name": ["My custom area"],
            "subtype": ["custom-area"],
            "source": ["custom"],
            "similarity_score": [1.0],
        }
    ),
}
