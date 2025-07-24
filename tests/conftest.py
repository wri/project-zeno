"""Test configuration and fixtures."""
import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.api.data_models import Base

# Test database settings
TEST_DB_URL = f"{os.getenv('DATABASE_URL')}_test"
ENGINE = create_engine(TEST_DB_URL)


@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Create test database and clear it after each test."""
    # Set up test database
    Base.metadata.create_all(bind=ENGINE)

    yield  # Run the tests

    # Clean databases
    Base.metadata.drop_all(bind=ENGINE)


def clear_tables():
    """Truncate all tables, except the 'users' table, after running each test."""
    Session = sessionmaker(
        bind=ENGINE,
        expire_on_commit=False
    )
    with Session() as session:
        for table in Base.metadata.sorted_tables:
            if table.name != "users":
                session.execute(
                    text(f"TRUNCATE {table.name} RESTART IDENTITY CASCADE;"),
                )
        session.commit()


@pytest.fixture(autouse=True, scope="function")
def test_db_session():
    yield ENGINE
    ENGINE.dispose()
    clear_tables()
