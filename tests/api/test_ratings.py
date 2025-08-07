"""Tests for ratings API endpoints."""
import pytest
import pytest_asyncio
import uuid
from httpx import AsyncClient

from src.api.app import app, fetch_user_from_rw_api
from src.api.data_models import UserOrm, ThreadOrm, RatingOrm
from src.api.schemas import UserModel
from tests.conftest import async_session_maker

# Mock user data for testing - using a Test User from the existing mock pattern
MOCK_USER_DATA = {
    "id": "test-user-1",
    "name": "Test User", 
    "email": "test@developmentseed.org",
    "createdAt": "2024-01-01T00:00:00Z",
    "updatedAt": "2024-01-01T00:00:00Z",
}

def mock_ratings_user():
    """Mock user for ratings tests."""
    return UserModel.model_validate(MOCK_USER_DATA)

@pytest.fixture
def ratings_user():
    """Override the fetch_user_from_rw_api dependency with our mock user."""
    app.dependency_overrides[fetch_user_from_rw_api] = mock_ratings_user
    yield
    # Clean up override after test
    app.dependency_overrides.pop(fetch_user_from_rw_api, None)

@pytest_asyncio.fixture
async def test_user_and_thread():
    """Create a test user and thread for testing."""
    from sqlalchemy import select
    unique_id = str(uuid.uuid4())[:8]
    
    async with async_session_maker() as session:
        # Check if test user already exists, if not create it
        stmt = select(UserOrm).filter_by(id=MOCK_USER_DATA["id"])
        result = await session.execute(stmt)
        user = result.scalars().first()
        
        if not user:
            user = UserOrm(
                id=MOCK_USER_DATA["id"],  # Use the mocked user ID so API can find the thread
                name=MOCK_USER_DATA["name"],
                email=MOCK_USER_DATA["email"]
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        
        # Create test thread that belongs to the mocked user
        thread = ThreadOrm(
            id=f"test-thread-{unique_id}",
            user_id=MOCK_USER_DATA["id"],  # Must match mocked user ID
            agent_id="test-agent", 
            name="Test Thread"
        )
        session.add(thread)
        await session.commit()
        await session.refresh(thread)
        
        return user, thread

@pytest.mark.asyncio
async def test_create_rating_success(test_user_and_thread, client: AsyncClient, ratings_user):
    """Test successfully creating a new rating."""
    user, thread = test_user_and_thread
    
    response = await client.post(
        "/api/ratings",
        json={
            "thread_id": thread.id,
            "trace_id": "test-trace-1", 
            "rating": 1
        },
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    # Note: The API uses the mocked user ID, not the DB user ID
    assert data["user_id"] == MOCK_USER_DATA["id"]
    assert data["thread_id"] == thread.id
    assert data["trace_id"] == "test-trace-1"
    assert data["rating"] == 1
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

@pytest.mark.asyncio
async def test_update_existing_rating(test_user_and_thread, client: AsyncClient, ratings_user):
    """Test updating an existing rating (upsert behavior)."""
    user, thread = test_user_and_thread
    
    # Create initial rating with the mocked user ID (not the DB user ID)
    async with async_session_maker() as session:
        existing_rating = RatingOrm(
            id="test-rating-1",
            user_id=MOCK_USER_DATA["id"],  # Use mocked user ID
            thread_id=thread.id,
            trace_id="test-trace-1",
            rating=1
        )
        session.add(existing_rating)
        await session.commit()
        original_created_at = existing_rating.created_at
    
    response = await client.post(
        "/api/ratings",
        json={
            "thread_id": thread.id,
            "trace_id": "test-trace-1",
            "rating": -1  # Change from thumbs up to thumbs down
        },
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == existing_rating.id  # Same rating ID
    assert data["rating"] == -1  # Updated rating
    assert data["created_at"] == original_created_at.isoformat()  # Created at unchanged

@pytest.mark.asyncio
async def test_create_rating_invalid_rating_value(test_user_and_thread, client: AsyncClient, ratings_user):
    """Test creating a rating with invalid rating value."""
    user, thread = test_user_and_thread
    
    response = await client.post(
        "/api/ratings",
        json={
            "thread_id": thread.id,
            "trace_id": "test-trace-1",
            "rating": 5  # Invalid rating (should be 1 or -1)
        },
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response.status_code == 422
    assert "Rating must be either 1 (thumbs up) or -1 (thumbs down)" in response.text

@pytest.mark.asyncio
async def test_create_rating_nonexistent_thread(test_user_and_thread, client: AsyncClient, ratings_user):
    """Test creating a rating for a thread that doesn't exist."""
    user, thread = test_user_and_thread
    
    response = await client.post(
        "/api/ratings",
        json={
            "thread_id": "nonexistent-thread",
            "trace_id": "test-trace-1",
            "rating": 1
        },
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response.status_code == 404
    assert "Thread not found or access denied" in response.json()["detail"]

@pytest.mark.asyncio
async def test_create_rating_thread_belongs_to_other_user(test_user_and_thread, client: AsyncClient, ratings_user):
    """Test creating a rating for a thread that belongs to another user."""
    user, thread = test_user_and_thread
    
    # Create another user's thread
    async with async_session_maker() as session:
        other_user = UserOrm(
            id="other-user-1",
            name="Other User",
            email="other@developmentseed.org"
        )
        session.add(other_user)
        
        other_thread = ThreadOrm(
            id="other-thread-1",
            user_id=other_user.id,
            agent_id="test-agent",
            name="Other Thread"
        )
        session.add(other_thread)
        await session.commit()

        response = await client.post(
            "/api/ratings",
            json={
                "thread_id": other_thread.id,  # Thread belongs to other user
                "trace_id": "test-trace-1",
                "rating": 1
            },
            headers={"Authorization": "Bearer test-token"}
        )
    
    assert response.status_code == 404
    assert "Thread not found or access denied" in response.json()["detail"]

@pytest.mark.asyncio
async def test_create_rating_unauthorized(test_user_and_thread, client: AsyncClient):
    """Test creating a rating without authorization."""
    user, thread = test_user_and_thread
    
    response = await client.post(
        "/api/ratings",
        json={
            "thread_id": thread.id,
            "trace_id": "test-trace-1",
            "rating": 1
        }
        # No Authorization header
    )
    
    assert response.status_code == 401  # Unauthorized

@pytest.mark.asyncio
async def test_create_rating_missing_fields(test_user_and_thread, client: AsyncClient, ratings_user):
    """Test creating a rating with missing required fields."""
    user, thread = test_user_and_thread
    
    # Missing trace_id
    response = await client.post(
        "/api/ratings",
        json={
            "thread_id": thread.id,
            "rating": 1
        },
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_create_multiple_ratings_same_user_different_traces(test_user_and_thread, client: AsyncClient, ratings_user):
    """Test creating multiple ratings for the same user but different traces."""
    user, thread = test_user_and_thread
    
    # Create first rating
    response1 = await client.post(
        "/api/ratings",
        json={
            "thread_id": thread.id,
            "trace_id": "test-trace-1",
            "rating": 1
        },
        headers={"Authorization": "Bearer test-token"}
    )
    
    # Create second rating for different trace
    response2 = await client.post(
        "/api/ratings",
        json={
            "thread_id": thread.id,
            "trace_id": "test-trace-2",
            "rating": -1
        },
        headers={"Authorization": "Bearer test-token"}
    )
    
    assert response1.status_code == 200
    assert response2.status_code == 200
    
    data1 = response1.json()
    data2 = response2.json()
    
    # Should be different ratings
    assert data1["id"] != data2["id"]
    assert data1["trace_id"] == "test-trace-1"
    assert data2["trace_id"] == "test-trace-2"
    assert data1["rating"] == 1
    assert data2["rating"] == -1