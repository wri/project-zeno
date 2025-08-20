"""Tests for thread-related endpoints and sharing functionality."""

import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_list_threads_requires_auth(client):
    """Test that listing threads requires authentication."""
    response = await client.get("/api/threads")
    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_threads_authenticated(
    client, auth_override, thread_factory
):
    """Test that authenticated users can list their threads."""
    user_id = "test-user-1"
    auth_override(user_id)

    # Create some threads for the user
    thread1 = await thread_factory(user_id)
    thread2 = await thread_factory(user_id)

    response = await client.get(
        "/api/threads", headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    threads = response.json()
    assert len(threads) == 2
    thread_ids = [t["id"] for t in threads]
    assert thread1.id in thread_ids
    assert thread2.id in thread_ids

    # Verify all threads have is_public field (should default to False after migration)
    for thread in threads:
        assert "is_public" in thread
        assert thread["is_public"] is False


@pytest.mark.asyncio
async def test_get_private_thread_requires_ownership(
    client, auth_override, thread_factory
):
    """Test that private threads require ownership to access."""
    owner_id = "owner-user"
    other_user_id = "other-user"

    # Create thread as owner
    auth_override(owner_id)
    thread = await thread_factory(owner_id)

    # Try to access as different user
    auth_override(other_user_id)
    response = await client.get(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404
    assert "Thread not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_private_thread_requires_auth(client, thread_factory):
    """Test that private threads require authentication."""
    user_id = "test-user"
    thread = await thread_factory(user_id)

    # Try to access without authentication
    response = await client.get(f"/api/threads/{thread.id}")

    assert response.status_code == 401
    assert "Missing Bearer token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_thread_name(client, auth_override, thread_factory):
    """Test updating thread name via PATCH."""
    user_id = "test-user"
    auth_override(user_id)
    thread = await thread_factory(user_id)

    new_name = "Updated Thread Name"
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"name": new_name},
    )

    assert response.status_code == 200
    updated_thread = response.json()
    assert updated_thread["name"] == new_name
    assert updated_thread["id"] == thread.id
    assert "is_public" in updated_thread
    assert updated_thread["is_public"] is False


@pytest.mark.asyncio
async def test_update_thread_to_public(client, auth_override, thread_factory):
    """Test making a thread public via PATCH."""
    user_id = "test-user"
    auth_override(user_id)
    thread = await thread_factory(user_id)

    # Make thread public
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": True},
    )

    assert response.status_code == 200
    updated_thread = response.json()
    assert updated_thread["is_public"] is True
    assert updated_thread["id"] == thread.id


@pytest.mark.asyncio
async def test_update_thread_to_private(client, auth_override, thread_factory):
    """Test making a public thread private via PATCH."""
    user_id = "test-user"
    auth_override(user_id)
    thread = await thread_factory(user_id)

    # First make it public
    await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": True},
    )

    # Then make it private again
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": False},
    )

    assert response.status_code == 200
    updated_thread = response.json()
    assert updated_thread["is_public"] is False


@pytest.mark.asyncio
async def test_update_thread_name_and_public_status(
    client, auth_override, thread_factory
):
    """Test updating both name and public status in single request."""
    user_id = "test-user"
    auth_override(user_id)
    thread = await thread_factory(user_id)

    new_name = "Public Thread"
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"name": new_name, "is_public": True},
    )

    assert response.status_code == 200
    updated_thread = response.json()
    assert updated_thread["name"] == new_name
    assert updated_thread["is_public"] is True


@pytest.mark.asyncio
async def test_access_public_thread_without_auth(
    client, auth_override, thread_factory
):
    """Test that public threads can be accessed without authentication."""
    user_id = "test-user"
    auth_override(user_id)
    thread = await thread_factory(user_id)

    # Make thread public
    await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": True},
    )

    # Access without authentication should work
    response = await client.get(f"/api/threads/{thread.id}")

    assert response.status_code == 200
    # Response should be streaming, so we just check that it doesn't error


@pytest.mark.asyncio
async def test_access_public_thread_different_user(
    client, auth_override, thread_factory
):
    """Test that public threads can be accessed by different users."""
    owner_id = "owner-user"
    other_user_id = "other-user"

    # Create thread as owner and make it public
    auth_override(owner_id)
    thread = await thread_factory(owner_id)

    await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": True},
    )

    # Access as different user should work
    auth_override(other_user_id)
    response = await client.get(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_cannot_update_other_users_thread(
    client, auth_override, thread_factory
):
    """Test that users cannot update threads they don't own."""
    owner_id = "owner-user"
    other_user_id = "other-user"

    # Create thread as owner
    auth_override(owner_id)
    thread = await thread_factory(owner_id)

    # Try to update as different user
    auth_override(other_user_id)
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": True},
    )

    assert response.status_code == 404
    assert "Thread not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_nonexistent_thread(client, auth_override):
    """Test updating a thread that doesn't exist."""
    auth_override("test-user")

    fake_thread_id = str(uuid.uuid4())
    response = await client.patch(
        f"/api/threads/{fake_thread_id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": True},
    )

    assert response.status_code == 404
    assert "Thread not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_nonexistent_thread(client, auth_override):
    """Test getting a thread that doesn't exist."""
    auth_override("test-user")

    fake_thread_id = str(uuid.uuid4())
    response = await client.get(
        f"/api/threads/{fake_thread_id}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404
    assert "Thread not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_nonexistent_public_thread_without_auth(client):
    """Test getting a nonexistent thread without auth returns 404."""
    fake_thread_id = str(uuid.uuid4())
    response = await client.get(f"/api/threads/{fake_thread_id}")

    assert response.status_code == 404
    assert "Thread not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_thread_removes_public_access(
    client, auth_override, thread_factory
):
    """Test that deleting a public thread removes public access."""
    user_id = "test-user"
    auth_override(user_id)
    thread = await thread_factory(user_id)

    # Make thread public
    await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": True},
    )

    # Verify public access works
    response = await client.get(f"/api/threads/{thread.id}")
    assert response.status_code == 200

    # Delete the thread - mock the dependency injection properly
    from src.agents.agents import fetch_checkpointer
    from src.api.app import app

    async def mock_checkpointer_func():
        mock = AsyncMock()
        mock.delete_thread = AsyncMock()
        return mock

    # Override the dependency
    original_dependency = app.dependency_overrides.get(fetch_checkpointer)
    app.dependency_overrides[fetch_checkpointer] = mock_checkpointer_func

    try:
        response = await client.delete(
            f"/api/threads/{thread.id}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 204
    finally:
        # Restore original dependency
        if original_dependency:
            app.dependency_overrides[fetch_checkpointer] = original_dependency
        else:
            app.dependency_overrides.pop(fetch_checkpointer, None)

    # Verify public access no longer works
    response = await client.get(f"/api/threads/{thread.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_invalid_is_public_values(client, auth_override, thread_factory):
    """Test that invalid is_public values are rejected."""
    user_id = "test-user"
    auth_override(user_id)
    thread = await thread_factory(user_id)

    # Test with invalid string value that can't be coerced to boolean
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": "invalid"},  # String that can't be coerced
    )

    assert response.status_code == 422  # Validation error

    # Test with numeric value
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": 123},  # Number instead of boolean
    )

    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_partial_update_preserves_other_fields(
    client, auth_override, thread_factory
):
    """Test that partial updates don't affect other fields."""
    user_id = "test-user"
    auth_override(user_id)
    thread = await thread_factory(user_id)

    original_name = thread.name

    # Update only is_public
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"is_public": True},
    )

    assert response.status_code == 200
    updated_thread = response.json()
    assert updated_thread["is_public"] is True
    assert updated_thread["name"] == original_name  # Name should be unchanged
    assert updated_thread["user_id"] == user_id  # Other fields unchanged


@pytest.mark.asyncio
async def test_thread_timestamps_behavior(client, auth_override, thread_factory):
    """Test that created_at and updated_at timestamps behave correctly."""
    user_id = "test-user-timestamps"
    auth_override(user_id)

    # Record time before creating thread
    before_create = datetime.now()
    
    # Create a thread
    thread = await thread_factory(user_id)
    
    # Record time after creating thread  
    after_create = datetime.now()

    # Verify created_at is set to approximately current time
    created_at = datetime.fromisoformat(thread.created_at.isoformat())
    updated_at = datetime.fromisoformat(thread.updated_at.isoformat())
    
    # created_at should be between before_create and after_create
    assert before_create <= created_at <= after_create
    
    # Initially, created_at and updated_at should be the same (or very close)
    time_diff = abs((updated_at - created_at).total_seconds())
    assert time_diff < 1  # Should be within 1 second
    
    # Store original timestamps
    original_created_at = created_at
    original_updated_at = updated_at
    
    # Wait a small amount to ensure timestamp difference
    await asyncio.sleep(0.1)
    
    # Update the thread via API
    before_update = datetime.now()
    response = await client.patch(
        f"/api/threads/{thread.id}",
        headers={"Authorization": "Bearer test-token"},
        json={"name": "Updated Thread Name"}
    )
    after_update = datetime.now()
    
    assert response.status_code == 200
    updated_thread_data = response.json()
    
    # Parse updated timestamps
    new_created_at = datetime.fromisoformat(updated_thread_data["created_at"])
    new_updated_at = datetime.fromisoformat(updated_thread_data["updated_at"])
    
    # created_at should NOT have changed
    assert new_created_at == original_created_at
    
    # updated_at should have changed and be recent
    assert new_updated_at != original_updated_at
    assert before_update <= new_updated_at <= after_update
    
    # updated_at should be after created_at
    assert new_updated_at > new_created_at
