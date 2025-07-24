"""Test configuration and fixtures."""
import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.api.data_models import Base

from src.api.app import app, get_session

# Test database settings
if (os.getenv('TEST_DATABASE_URL')):
    TEST_DB_URL = os.getenv("TEST_DATABASE_URL")
else:
    TEST_DB_URL = f"{os.getenv('DATABASE_URL')}_test"
ENGINE = create_engine(TEST_DB_URL)
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


def get_session_override():
    with Session() as session:
        yield session  # Run the tests


app.dependency_overrides[get_session] = get_session_override


@pytest.fixture(scope="function", autouse=True)
def test_db():
    """Create test database and clear it after each test."""
    # Set up test database
    Base.metadata.create_all(bind=ENGINE)
    yield
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
