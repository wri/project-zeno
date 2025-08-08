"""Tests for ratings API endpoints."""
import pytest
from httpx import AsyncClient

from src.api.data_models import UserOrm


@pytest.mark.asyncio
async def test_create_rating_success(
    thread_factory, client: AsyncClient, user: UserOrm, auth_override
):
    """Test successfully creating a new rating."""
    thread = await thread_factory(user.id)
    auth_override(user.id)

    response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-1",
            "rating": 1,
            "comment": "Great response!"
        },
        headers={"Authorization": "Bearer test-user-wri-token"}
    )

    assert response.status_code == 200
    data = response.json()
    # Note: The API uses the mocked user ID, not the DB user ID
    assert data["user_id"] == user.id
    assert data["thread_id"] == thread.id
    assert data["trace_id"] == "test-trace-1"
    assert data["rating"] == 1
    assert data["comment"] == "Great response!"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

    update_res = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-1",
            "rating": -1  # Change from thumbs up to thumbs down
        },
        headers={"Authorization": "Bearer test-user-wri-token"}
    )

    assert update_res.status_code == 200
    update_data = update_res.json()
    assert update_data["id"] == data["id"]  # Same rating ID
    assert update_data["rating"] == -1  # Updated rating
    assert update_data["created_at"] == data["created_at"]


@pytest.mark.asyncio
async def test_create_rating_invalid_rating_value(
    thread_factory, user: UserOrm, client: AsyncClient, auth_override
):
    """Test creating a rating with invalid rating value."""
    thread = await thread_factory(user.id)
    auth_override(user.id)

    response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-1",
            "rating": 5  # Invalid rating (should be 1 or -1)
        },
        headers={"Authorization": "Bearer test-user-wri-token"}
    )

    assert response.status_code == 422
    assert "Rating must be either 1 (thumbs up) or -1 (thumbs down)" in response.text


@pytest.mark.asyncio
async def test_create_rating_nonexistent_thread(
    client: AsyncClient, auth_override
):
    """Test creating a rating for a thread that doesn't exist."""
    auth_override("test-user-wri")
    response = await client.post(
        "/api/threads/nonexistent-thread/rating",
        json={
            "trace_id": "test-trace-1",
            "rating": 1
        },
        headers={"Authorization": "Bearer test-user-wri-token"}
    )

    assert response.status_code == 404
    assert "Thread not found or access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_rating_thread_belongs_to_other_user(
    thread_factory,
    user: UserOrm,
    user_ds: UserOrm,
    client: AsyncClient,
    auth_override
):
    """Test creating a rating for a thread that belongs to another user."""
    # Execute the test with a user that is not the owner of the thread
    thread = await thread_factory(user_ds.id)
    auth_override(user.id)

    response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-1",
            "rating": 1
        },
        headers={"Authorization": "Bearer test-user-wri-token"}
    )

    assert response.status_code == 404
    assert "Thread not found or access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_rating_unauthorized(
    user: UserOrm, thread_factory, client: AsyncClient
):
    """Test creating a rating without authorization."""
    thread = await thread_factory(user.id)

    response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-1",
            "rating": 1
        }
        # No Authorization header and not auth_override
    )

    assert response.status_code == 401  # Unauthorized


@pytest.mark.asyncio
async def test_create_rating_missing_fields(
    auth_override, thread_factory, user: UserOrm, client: AsyncClient
):
    """Test creating a rating with missing required fields."""
    thread = await thread_factory(user.id)
    auth_override(user.id)

    # Missing trace_id
    response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "rating": 1
        },
        headers={"Authorization": "Bearer test-user-wri-token"}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_multiple_ratings_same_user_different_traces(
    thread_factory, user: UserOrm, client: AsyncClient, auth_override
):
    """Test creating multiple ratings for the same user, but different traces.
    """
    thread = await thread_factory(user.id)
    auth_override(user.id)

    # Create first rating
    response1 = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-3",
            "rating": 1,
            "comment": "Great response!",
        },
        headers={"Authorization": "Bearer test-user-wri-token"},
    )
    assert response1.status_code == 200

    # Create second rating for different trace
    response2 = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={"trace_id": "test-trace-4", "rating": -1},
        headers={"Authorization": "Bearer test-user-wri-token"},
    )
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    # Should be different ratings
    assert data1["id"] != data2["id"]
    assert data1["trace_id"] == "test-trace-3"
    assert data2["trace_id"] == "test-trace-4"
    assert data1["rating"] == 1
    assert data2["rating"] == -1


@pytest.mark.asyncio
async def test_create_update_rating_with_comment(
    thread_factory, user, client: AsyncClient, auth_override
):
    """Test creating a rating with a comment."""
    thread = await thread_factory(user.id)
    auth_override(user.id)

    response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-comment",
            "rating": 1,
            "comment": "This is a test comment"
        },
        headers={"Authorization": "Bearer test-user-wri-token"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["comment"] == "This is a test comment"

    # Update the rating with new comment
    response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-comment",
            "rating": 1,
            "comment": "Updated comment"
        },
        headers={"Authorization": "Bearer test-user-wri-token"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["comment"] == "Updated comment"
