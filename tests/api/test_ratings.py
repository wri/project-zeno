"""Tests for ratings API endpoints."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api import app as api
from src.api.data_models import UserOrm, ThreadOrm, RatingOrm

# Use the original app with its dependencies and middleware
client = TestClient(api.app)

# Mock user data for testing
MOCK_USER = {
    "id": "test-user-1",
    "name": "Test User",
    "email": "test@developmentseed.org",
    "createdAt": "2024-01-01T00:00:00Z",
    "updatedAt": "2024-01-01T00:00:00Z"
}

def mock_rw_api_response(user_data):
    """Helper to create a mock response object."""
    class MockResponse:
        def __init__(self, json_data, status_code):
            self.json_data = json_data
            self.status_code = status_code
            self.text = str(json_data)

        def json(self):
            return self.json_data

    return MockResponse(user_data, 200)

@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the user info cache before each test."""
    api._user_info_cache.clear()

@pytest.fixture
def test_user_and_thread(db_session: Session):
    """Create a test user and thread for testing."""
    # Create test user
    user = UserOrm(
        id=MOCK_USER["id"],
        name=MOCK_USER["name"],
        email=MOCK_USER["email"]
    )
    db_session.add(user)
    
    # Create test thread
    thread = ThreadOrm(
        id="test-thread-1",
        user_id=user.id,
        agent_id="test-agent",
        name="Test Thread"
    )
    db_session.add(thread)
    db_session.commit()
    
    return user, thread

def test_create_rating_success(test_user_and_thread, db_session: Session):
    """Test successfully creating a new rating."""
    user, thread = test_user_and_thread
    
    with patch('requests.get') as mock_get:
        mock_response = mock_rw_api_response(MOCK_USER)
        mock_get.return_value = mock_response
        
        response = client.post(
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
    assert data["user_id"] == user.id
    assert data["thread_id"] == thread.id
    assert data["trace_id"] == "test-trace-1"
    assert data["rating"] == 1
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

def test_update_existing_rating(test_user_and_thread, db_session: Session):
    """Test updating an existing rating (upsert behavior)."""
    user, thread = test_user_and_thread
    
    # Create initial rating
    existing_rating = RatingOrm(
        id="test-rating-1",
        user_id=user.id,
        thread_id=thread.id,
        trace_id="test-trace-1",
        rating=1
    )
    db_session.add(existing_rating)
    db_session.commit()
    original_created_at = existing_rating.created_at
    
    with patch('requests.get') as mock_get:
        mock_response = mock_rw_api_response(MOCK_USER)
        mock_get.return_value = mock_response
        
        response = client.post(
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
    # Updated at should be different, but we won't test exact time

def test_create_rating_invalid_rating_value(test_user_and_thread, db_session: Session):
    """Test creating a rating with invalid rating value."""
    user, thread = test_user_and_thread
    
    with patch('requests.get') as mock_get:
        mock_response = mock_rw_api_response(MOCK_USER)
        mock_get.return_value = mock_response
        
        response = client.post(
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

def test_create_rating_nonexistent_thread(test_user_and_thread, db_session: Session):
    """Test creating a rating for a thread that doesn't exist."""
    user, thread = test_user_and_thread
    
    with patch('requests.get') as mock_get:
        mock_response = mock_rw_api_response(MOCK_USER)
        mock_get.return_value = mock_response
        
        response = client.post(
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

def test_create_rating_thread_belongs_to_other_user(test_user_and_thread, db_session: Session):
    """Test creating a rating for a thread that belongs to another user."""
    user, thread = test_user_and_thread
    
    # Create another user's thread
    other_user = UserOrm(
        id="other-user-1",
        name="Other User",
        email="other@developmentseed.org"
    )
    db_session.add(other_user)
    
    other_thread = ThreadOrm(
        id="other-thread-1",
        user_id=other_user.id,
        agent_id="test-agent",
        name="Other Thread"
    )
    db_session.add(other_thread)
    db_session.commit()
    
    with patch('requests.get') as mock_get:
        mock_response = mock_rw_api_response(MOCK_USER)
        mock_get.return_value = mock_response
        
        response = client.post(
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

def test_create_rating_unauthorized(test_user_and_thread, db_session: Session):
    """Test creating a rating without authorization."""
    user, thread = test_user_and_thread
    
    response = client.post(
        "/api/ratings",
        json={
            "thread_id": thread.id,
            "trace_id": "test-trace-1",
            "rating": 1
        }
        # No Authorization header
    )
    
    assert response.status_code == 422  # FastAPI validation error

def test_create_rating_missing_fields(test_user_and_thread, db_session: Session):
    """Test creating a rating with missing required fields."""
    user, thread = test_user_and_thread
    
    with patch('requests.get') as mock_get:
        mock_response = mock_rw_api_response(MOCK_USER)
        mock_get.return_value = mock_response
        
        # Missing trace_id
        response = client.post(
            "/api/ratings",
            json={
                "thread_id": thread.id,
                "rating": 1
            },
            headers={"Authorization": "Bearer test-token"}
        )
    
    assert response.status_code == 422

def test_create_multiple_ratings_same_user_different_traces(test_user_and_thread, db_session: Session):
    """Test creating multiple ratings for the same user but different traces."""
    user, thread = test_user_and_thread
    
    with patch('requests.get') as mock_get:
        mock_response = mock_rw_api_response(MOCK_USER)
        mock_get.return_value = mock_response
        
        # Create first rating
        response1 = client.post(
            "/api/ratings",
            json={
                "thread_id": thread.id,
                "trace_id": "test-trace-1",
                "rating": 1
            },
            headers={"Authorization": "Bearer test-token"}
        )
        
        # Create second rating for different trace
        response2 = client.post(
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