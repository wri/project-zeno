import pytest


# Override the root autouse DB fixtures so unit tests don't require a live database.
@pytest.fixture(scope="session", autouse=True)
def test_db():
    yield


@pytest.fixture(scope="function", autouse=True)
def test_db_session():
    yield
