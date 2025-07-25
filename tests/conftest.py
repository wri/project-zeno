"""Test configuration and fixtures."""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.api.data_models import Base

from src.api.app import app, get_session, fetch_user_from_rw_api
from src.api.data_models import UserOrm, UserModel

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


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


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


@pytest.fixture(scope="session")
def user(username, session):
    with get_session_override() as session:
        user = UserOrm(
            name=username,
            email="admin@wri.org",
        )
        session.add(user)
        session.commit()


def set_wri_user():
    return UserModel.model_validate({
        "id": "test-user-2",
        "name": "WRI User",
        "email": "test@wri.org",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
    })


@pytest.fixture(scope="function")
def wri_user():
    app.dependency_overrides[fetch_user_from_rw_api] = set_wri_user
