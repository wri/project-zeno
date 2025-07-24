"""Test configuration and fixtures."""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import pytest
from sqlalchemy.orm import sessionmaker
from alembic.config import Config
from alembic import command
from pathlib import Path

# Test database settings
TEST_DB_NAME = "zeno_test"
DEFAULT_DB_URL = "postgresql+psycopg://postgres@localhost:5432/postgres"
TEST_DB_URL = f"postgresql+asyncpg://postgres@localhost:5432/{TEST_DB_NAME}"

def run_migrations(database_url: str) -> None:
    """Run all alembic migrations."""
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", "db/alembic")
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_cfg, "head")

def create_test_database() -> None:
    """Create a test database."""
    # Connect to default postgres database
    engine = create_engine(DEFAULT_DB_URL)
    
    # Need to be outside a transaction for database drop/create
    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        # Drop test database if it exists and create it fresh
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    
    engine.dispose()
    
    # Run migrations on test database
    run_migrations(TEST_DB_URL)

def drop_test_database() -> None:
    """Drop the test database."""
    engine = create_engine(DEFAULT_DB_URL)
    
    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
    
    engine.dispose()

@pytest.fixture(scope="session", autouse=True)
def test_db():
    """Create test database and run migrations."""
    # Save original DATABASE_URL
    original_db_url = os.environ.get("DATABASE_URL")
    
    # Set up test database
    create_test_database()
    os.environ["DATABASE_URL"] = TEST_DB_URL
    
    yield  # Run the tests
    
    # Clean up
    if original_db_url:
        os.environ["DATABASE_URL"] = original_db_url
    drop_test_database()

@pytest.fixture(scope="function")
async def db_session():
    """Create a new async database session for a test."""
    engine = create_async_engine(TEST_DB_URL)
    AsyncSessionLocal = sessionmaker(class_=AsyncSession, expire_on_commit=False, bind=engine)
    
    async with AsyncSessionLocal() as session:
        async with session.begin():  # Automatic transaction management
            yield session
            await session.rollback()  # Rollback any changes after test
    
    await engine.dispose()
