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
            "comment": "Great response!",
        },
        headers={"Authorization": "Bearer test-user-wri-token"},
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
            "rating": -1,  # Change from thumbs up to thumbs down
        },
        headers={"Authorization": "Bearer test-user-wri-token"},
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
            "rating": 5,  # Invalid rating (should be 1 or -1)
        },
        headers={"Authorization": "Bearer test-user-wri-token"},
    )

    assert response.status_code == 422
    assert (
        "Rating must be either 1 (thumbs up) or -1 (thumbs down)"
        in response.text
    )


@pytest.mark.asyncio
async def test_create_rating_nonexistent_thread(
    client: AsyncClient, auth_override
):
    """Test creating a rating for a thread that doesn't exist."""
    auth_override("test-user-wri")
    response = await client.post(
        "/api/threads/nonexistent-thread/rating",
        json={"trace_id": "test-trace-1", "rating": 1},
        headers={"Authorization": "Bearer test-user-wri-token"},
    )

    assert response.status_code == 404
    assert "Thread not found or access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_rating_thread_belongs_to_other_user(
    thread_factory,
    user: UserOrm,
    user_ds: UserOrm,
    client: AsyncClient,
    auth_override,
):
    """Test creating a rating for a thread that belongs to another user."""
    # Execute the test with a user that is not the owner of the thread
    thread = await thread_factory(user_ds.id)
    auth_override(user.id)

    response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={"trace_id": "test-trace-1", "rating": 1},
        headers={"Authorization": "Bearer test-user-wri-token"},
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
        json={"trace_id": "test-trace-1", "rating": 1},
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
        json={"rating": 1},
        headers={"Authorization": "Bearer test-user-wri-token"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_multiple_ratings_same_user_different_traces(
    thread_factory, user: UserOrm, client: AsyncClient, auth_override
):
    """Test creating multiple ratings for the same user, but different traces."""
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
            "comment": "This is a test comment",
        },
        headers={"Authorization": "Bearer test-user-wri-token"},
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
            "comment": "Updated comment",
        },
        headers={"Authorization": "Bearer test-user-wri-token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["comment"] == "Updated comment"


@pytest.mark.asyncio
async def test_get_thread_ratings_empty(
    thread_factory, user: UserOrm, client: AsyncClient, auth_override
):
    """Test getting ratings for a thread with no ratings."""
    thread = await thread_factory(user.id)
    auth_override(user.id)

    response = await client.get(
        f"/api/threads/{thread.id}/rating",
        headers={"Authorization": "Bearer test-user-wri-token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data == []


@pytest.mark.asyncio
async def test_get_thread_ratings_with_ratings(
    thread_factory, user: UserOrm, client: AsyncClient, auth_override
):
    """Test getting ratings for a thread that has ratings."""
    thread = await thread_factory(user.id)
    auth_override(user.id)

    # Create multiple ratings for different traces in the thread
    rating_data = [
        {"trace_id": "trace-1", "rating": 1, "comment": "Good response"},
        {"trace_id": "trace-2", "rating": -1, "comment": "Bad response"},
        {"trace_id": "trace-3", "rating": 1},  # No comment
    ]

    created_ratings = []
    for data in rating_data:
        response = await client.post(
            f"/api/threads/{thread.id}/rating",
            json=data,
            headers={"Authorization": "Bearer test-user-wri-token"},
        )
        assert response.status_code == 200
        created_ratings.append(response.json())

    # Get all ratings for the thread
    response = await client.get(
        f"/api/threads/{thread.id}/rating",
        headers={"Authorization": "Bearer test-user-wri-token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3

    # Verify all ratings are returned and ordered by created_at
    trace_ids = [rating["trace_id"] for rating in data]
    assert "trace-1" in trace_ids
    assert "trace-2" in trace_ids
    assert "trace-3" in trace_ids

    # Check specific rating details
    rating_1 = next(r for r in data if r["trace_id"] == "trace-1")
    assert rating_1["rating"] == 1
    assert rating_1["comment"] == "Good response"

    rating_2 = next(r for r in data if r["trace_id"] == "trace-2")
    assert rating_2["rating"] == -1
    assert rating_2["comment"] == "Bad response"

    rating_3 = next(r for r in data if r["trace_id"] == "trace-3")
    assert rating_3["rating"] == 1
    assert rating_3["comment"] is None


@pytest.mark.asyncio
async def test_get_thread_ratings_nonexistent_thread(
    client: AsyncClient, auth_override
):
    """Test getting ratings for a thread that doesn't exist."""
    auth_override("test-user-wri")

    response = await client.get(
        "/api/threads/nonexistent-thread/rating",
        headers={"Authorization": "Bearer test-user-wri-token"},
    )

    assert response.status_code == 404
    assert "Thread not found or access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_thread_ratings_thread_belongs_to_other_user(
    thread_factory,
    user: UserOrm,
    user_ds: UserOrm,
    client: AsyncClient,
    auth_override,
):
    """Test getting ratings for a thread that belongs to another user."""
    thread = await thread_factory(user_ds.id)
    auth_override(user.id)

    response = await client.get(
        f"/api/threads/{thread.id}/rating",
        headers={"Authorization": "Bearer test-user-wri-token"},
    )

    assert response.status_code == 404
    assert "Thread not found or access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_thread_ratings_unauthorized(
    user: UserOrm, thread_factory, client: AsyncClient
):
    """Test getting ratings without authorization."""
    thread = await thread_factory(user.id)

    response = await client.get(
        f"/api/threads/{thread.id}/rating",
        # No Authorization header
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_full_flow_create_and_get_ratings(
    thread_factory, user: UserOrm, client: AsyncClient, auth_override
):
    """Test the full flow: create ratings then retrieve them."""
    thread = await thread_factory(user.id)
    auth_override(user.id)

    # Initially, thread should have no ratings
    response = await client.get(
        f"/api/threads/{thread.id}/rating",
        headers={"Authorization": "Bearer test-user-wri-token"},
    )
    assert response.status_code == 200
    assert response.json() == []

    # Create a rating
    create_response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-flow",
            "rating": 1,
            "comment": "Initial rating",
        },
        headers={"Authorization": "Bearer test-user-wri-token"},
    )
    assert create_response.status_code == 200
    created_rating = create_response.json()

    # Get ratings - should now have one rating
    get_response = await client.get(
        f"/api/threads/{thread.id}/rating",
        headers={"Authorization": "Bearer test-user-wri-token"},
    )
    assert get_response.status_code == 200
    ratings = get_response.json()
    assert len(ratings) == 1
    assert ratings[0]["trace_id"] == "test-trace-flow"
    assert ratings[0]["rating"] == 1
    assert ratings[0]["comment"] == "Initial rating"
    assert ratings[0]["id"] == created_rating["id"]

    # Update the rating
    update_response = await client.post(
        f"/api/threads/{thread.id}/rating",
        json={
            "trace_id": "test-trace-flow",
            "rating": -1,
            "comment": "Updated rating",
        },
        headers={"Authorization": "Bearer test-user-wri-token"},
    )
    assert update_response.status_code == 200

    # Get ratings again - should still have one rating but updated
    final_get_response = await client.get(
        f"/api/threads/{thread.id}/rating",
        headers={"Authorization": "Bearer test-user-wri-token"},
    )
    assert final_get_response.status_code == 200
    final_ratings = final_get_response.json()
    assert len(final_ratings) == 1
    assert final_ratings[0]["trace_id"] == "test-trace-flow"
    assert final_ratings[0]["rating"] == -1
    assert final_ratings[0]["comment"] == "Updated rating"
    assert (
        final_ratings[0]["id"] == created_rating["id"]
    )  # Same ID (updated, not created new)
