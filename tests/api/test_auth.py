"""Tests for authentication-related endpoints."""

import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest

# Import the API app directly from the src package
from src.api import app as api

from .mock import mock_rw_api_response


@contextmanager
def domain_allowlist(domains: str):
    """Context manager to set and reset DOMAINS_ALLOWLIST."""
    domain_list = domains.split(",")
    try:
        with patch.object(api.APISettings, "domains_allowlist_str", domains):
            yield domain_list
    finally:
        pass


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the user info cache before each test."""
    api._user_info_cache.clear()


@pytest.mark.parametrize(
    "username,expected_status,expected_error",
    [
        ("Test User", 200, None),  # developmentseed.org user should succeed
        ("WRI User", 200, None),  # wri.org user should succeed
        (
            "Unauthorized User",
            403,
            "User not allowed to access this API",
        ),  # unauthorized domain should fail
    ],
)
@pytest.mark.asyncio
async def test_email_domain_authorization(
    username, expected_status, expected_error, client
):
    """Test that only users with allowed email domains can access the API."""
    with domain_allowlist("developmentseed.org,wri.org"):
        with patch.object(
            api.APISettings, "allow_public_signups", False
        ):  # Disable public signups for original behavior
            with patch("httpx.AsyncClient") as mock_client_class:
                # Mock the AsyncClient context manager and get method
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                mock_client.get.return_value = mock_rw_api_response(username)

                # Test the auth endpoint
                response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"},
                )

            assert response.status_code == expected_status

            if expected_error:
                assert expected_error in response.json()["detail"]
            else:
                # For successful requests, verify the user data is returned correctly
                user_response = response.json()
                assert user_response["name"] == username


@pytest.mark.asyncio
async def test_missing_bearer_token(client):
    """Test that requests without a Bearer token are rejected."""
    with domain_allowlist("developmentseed.org,wri.org"):
        with patch.object(
            api.APISettings, "allow_public_signups", False
        ):  # Ensure consistent behavior
            response = await client.get(
                "/api/auth/me",
                headers={
                    "Authorization": "test-token"
                },  # Missing "Bearer" prefix
            )
            assert response.status_code == 401
            assert (
                "Missing Bearer token in Authorization header"
                in response.json()["detail"]
            )


@pytest.mark.asyncio
async def test_missing_authorization_header(client):
    """Test that requests without an Authorization header are rejected."""
    with patch.object(
        api.APISettings, "allow_public_signups", False
    ):  # Ensure consistent behavior
        os.environ["DOMAINS_ALLOWLIST"] = "developmentseed.org,wri.org"
        response = await client.get("/api/auth/me")  # No Authorization header
        assert response.status_code == 401
        assert (
            "Missing Bearer token in Authorization header"
            in response.json()["detail"]
        )


@pytest.mark.asyncio
async def test_user_cant_override_email_domain_authorization(client):
    """Test that only users cant override email domain authorization through query params."""
    with domain_allowlist("developmentseed.org,wri.org"):
        with patch.object(
            api.APISettings, "allow_public_signups", False
        ):  # Disable public signups for original behavior
            with patch("httpx.AsyncClient") as mock_client_class:
                # Mock the AsyncClient context manager and get method
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                mock_client.get.return_value = mock_rw_api_response(
                    "Unauthorized User"
                )

                # Test the auth endpoint
                response = await client.get(
                    "/api/auth/me?domains_allowlist=unauthorized.com",
                    headers={"Authorization": "Bearer test-token"},
                )

            assert response.status_code == 403
            assert (
                "User not allowed to access this API"
                in response.json()["detail"]
            )


@pytest.mark.asyncio
async def test_email_whitelist_allows_access(client):
    """Test that users on email whitelist can access even if domain not allowed."""
    from src.api.data_models import WhitelistedUserOrm
    from tests.conftest import async_session_maker

    # Add test email to whitelist
    async with async_session_maker() as session:
        whitelisted_user = WhitelistedUserOrm(email="test@gmail.com")
        session.add(whitelisted_user)
        await session.commit()

    with domain_allowlist(
        "developmentseed.org,wri.org"
    ):  # gmail.com not in domain list
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            # Mock user with gmail.com email (not in domain allowlist but in email whitelist)
            mock_response = mock_rw_api_response("Gmail User")
            mock_response.json_data["email"] = "test@gmail.com"
            mock_client.get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["email"] == "test@gmail.com"


@pytest.mark.asyncio
async def test_email_whitelist_case_insensitive(client):
    """Test that email whitelist matching is case insensitive."""
    from src.api.data_models import WhitelistedUserOrm
    from tests.conftest import async_session_maker

    # Add lowercase email to whitelist
    async with async_session_maker() as session:
        whitelisted_user = WhitelistedUserOrm(email="casetest@example.com")
        session.add(whitelisted_user)
        await session.commit()

    with domain_allowlist(
        "developmentseed.org"
    ):  # example.com not in domain list
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            # Mock user with uppercase email - create fresh mock
            mock_response = mock_rw_api_response("Gmail User")
            mock_response.json_data = {
                "id": "test-user-casetest",
                "name": "Case Test User",
                "email": "CASETEST@EXAMPLE.COM",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
            }
            mock_client.get.return_value = mock_response

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

        assert response.status_code == 200


@pytest.mark.asyncio
async def test_domain_whitelist_still_works_with_email_feature(client):
    """Test that existing domain whitelist functionality is preserved."""
    # Clear cache to ensure clean state
    api._user_info_cache.clear()

    with domain_allowlist("developmentseed.org,wri.org"):
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = (
                mock_client_class.return_value.__aenter__.return_value
            )
            mock_client.get.return_value = mock_rw_api_response("Test User")

            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["name"] == "Test User"


@pytest.mark.asyncio
async def test_user_blocked_when_not_in_domain_or_email_whitelist(client):
    """Test that users are blocked when not in either domain or email whitelist and public signups disabled."""
    with domain_allowlist("developmentseed.org,wri.org"):
        with patch.object(
            api.APISettings, "allow_public_signups", False
        ):  # Disable public signups
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                # Mock user with unauthorized domain and not in email whitelist
                mock_response = mock_rw_api_response("Unauthorized User")
                mock_response.json_data["email"] = "test@blocked.com"
                mock_client.get.return_value = mock_response

                response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"},
                )

            assert response.status_code == 403
            assert (
                "User not allowed to access this API"
                in response.json()["detail"]
            )


@pytest.mark.asyncio
async def test_public_signup_allowed_when_under_limit(client):
    """Test that public users can sign up when under the limit and public signups enabled."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm
    from tests.conftest import async_session_maker

    # Pre-populate with 2 users
    async with async_session_maker() as session:
        user1 = UserOrm(id="existing-1", name="User 1", email="user1@test.com")
        user2 = UserOrm(id="existing-2", name="User 2", email="user2@test.com")
        session.add_all([user1, user2])
        await session.commit()

    with domain_allowlist(""):  # No domain whitelist
        with patch.object(api.APISettings, "allow_public_signups", True):
            with patch.object(
                api.APISettings, "max_user_signups", 5
            ):  # Limit of 5, currently have 2
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = (
                        mock_client_class.return_value.__aenter__.return_value
                    )
                    # Mock public user (not in whitelist)
                    mock_response = mock_rw_api_response("Test User")
                    mock_response.json_data = {
                        "id": "public-user-123",
                        "name": "Public User",
                        "email": "publicuser@gmail.com",
                        "createdAt": "2024-01-01T00:00:00Z",
                        "updatedAt": "2024-01-01T00:00:00Z",
                    }
                    mock_client.get.return_value = mock_response

                    response = await client.get(
                        "/api/auth/me",
                        headers={"Authorization": "Bearer test-token"},
                    )

            assert response.status_code == 200
            user_data = response.json()
            assert user_data["id"] == "public-user-123"


@pytest.mark.asyncio
async def test_signup_limit_blocks_new_user_when_at_limit(client):
    """Test that new users are blocked when signup limit is reached."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm
    from tests.conftest import async_session_maker

    # Pre-populate to reach the limit (2 users)
    async with async_session_maker() as session:
        for i in range(2):
            user = UserOrm(
                id=f"existing-{i}", name=f"User {i}", email=f"user{i}@test.com"
            )
            session.add(user)
        await session.commit()

    with domain_allowlist(""):  # No domain whitelist
        with patch.object(api.APISettings, "allow_public_signups", True):
            with patch.object(
                api.APISettings, "max_user_signups", 2
            ):  # Limit of 2, currently have 2
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = (
                        mock_client_class.return_value.__aenter__.return_value
                    )
                    # Mock public user trying to sign up
                    mock_response = mock_rw_api_response("Test User")
                    mock_response.json_data = {
                        "id": "blocked-user-456",
                        "name": "Blocked User",
                        "email": "blocked@gmail.com",
                        "createdAt": "2024-01-01T00:00:00Z",
                        "updatedAt": "2024-01-01T00:00:00Z",
                    }
                    mock_client.get.return_value = mock_response

                    response = await client.get(
                        "/api/auth/me",
                        headers={"Authorization": "Bearer test-token"},
                    )

        assert response.status_code == 403
        assert "signups are currently closed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_public_signup_blocked_when_disabled(client):
    """Test that public users are blocked when public signups are disabled."""
    from unittest.mock import patch

    with domain_allowlist(""):  # No domain whitelist
        with patch.object(api.APISettings, "allow_public_signups", False):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                # Mock public user
                mock_response = mock_rw_api_response("Test User")
                mock_response.json_data = {
                    "id": "public-user-456",
                    "name": "Public User",
                    "email": "public@gmail.com",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                }
                mock_client.get.return_value = mock_response

                response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"},
                )

        assert response.status_code == 403
        assert (
            "User not allowed to access this API" in response.json()["detail"]
        )


@pytest.mark.asyncio
async def test_signup_limit_unlimited_when_negative(client):
    """Test that negative MAX_USER_SIGNUPS means unlimited signups."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm
    from tests.conftest import async_session_maker

    # Pre-populate with many users
    async with async_session_maker() as session:
        for i in range(100):
            user = UserOrm(
                id=f"existing-{i}", name=f"User {i}", email=f"user{i}@test.com"
            )
            session.add(user)
        await session.commit()

    with domain_allowlist(""):  # No domain whitelist
        with patch.object(api.APISettings, "allow_public_signups", True):
            with patch.object(
                api.APISettings, "max_user_signups", -1
            ):  # Unlimited
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = (
                        mock_client_class.return_value.__aenter__.return_value
                    )
                    mock_response = mock_rw_api_response("Test User")
                    mock_response.json_data = {
                        "id": "new-unlimited-user",
                        "name": "New User",
                        "email": "newuser@gmail.com",
                        "createdAt": "2024-01-01T00:00:00Z",
                        "updatedAt": "2024-01-01T00:00:00Z",
                    }
                    mock_client.get.return_value = mock_response

                    response = await client.get(
                        "/api/auth/me",
                        headers={"Authorization": "Bearer test-token"},
                    )

            assert response.status_code == 200


@pytest.mark.asyncio
async def test_whitelisted_user_bypasses_signup_limit(client):
    """Test that whitelisted users can sign up even when limit is reached."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm, WhitelistedUserOrm
    from tests.conftest import async_session_maker

    # Pre-populate to reach limit and add user to email whitelist
    async with async_session_maker() as session:
        # Add users to reach limit
        for i in range(2):
            user = UserOrm(
                id=f"existing-{i}", name=f"User {i}", email=f"user{i}@test.com"
            )
            session.add(user)
        # Add email to whitelist
        whitelisted = WhitelistedUserOrm(email="whitelisted@gmail.com")
        session.add(whitelisted)
        await session.commit()

    with domain_allowlist(
        "developmentseed.org"
    ):  # gmail.com not in domain list
        with patch.object(
            api.APISettings, "max_user_signups", 2
        ):  # Limit of 2, currently have 2
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                # Mock whitelisted user
                mock_response = mock_rw_api_response("Test User")
                mock_response.json_data = {
                    "id": "whitelisted-user-789",
                    "name": "Whitelisted User",
                    "email": "whitelisted@gmail.com",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                }
                mock_client.get.return_value = mock_response

                response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"},
                )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["email"] == "whitelisted@gmail.com"


@pytest.mark.asyncio
async def test_domain_whitelisted_user_bypasses_signup_limit(client):
    """Test that domain whitelisted users can sign up even when limit is reached."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm
    from tests.conftest import async_session_maker

    # Pre-populate to reach limit
    async with async_session_maker() as session:
        for i in range(3):
            user = UserOrm(
                id=f"existing-{i}", name=f"User {i}", email=f"user{i}@test.com"
            )
            session.add(user)
        await session.commit()

    with domain_allowlist("developmentseed.org,wri.org"):
        with patch.object(
            api.APISettings, "max_user_signups", 3
        ):  # Limit of 3, currently have 3
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                # Mock user from whitelisted domain
                mock_response = mock_rw_api_response("Test User")
                mock_response.json_data = {
                    "id": "domain-user-456",
                    "name": "Domain User",
                    "email": "domainuser@wri.org",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                }
                mock_client.get.return_value = mock_response

                response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"},
                )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["email"] == "domainuser@wri.org"


@pytest.mark.asyncio
async def test_existing_user_can_login_when_over_limit(client):
    """Test that existing users can always login even when over the signup limit."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm
    from tests.conftest import async_session_maker

    # Pre-populate with existing user and others to exceed limit
    async with async_session_maker() as session:
        existing_user = UserOrm(
            id="existing-user",
            name="Existing User",
            email="existing@developmentseed.org",
        )
        session.add(existing_user)
        for i in range(5):
            user = UserOrm(
                id=f"other-{i}", name=f"User {i}", email=f"user{i}@test.com"
            )
            session.add(user)
        await session.commit()

    with domain_allowlist("developmentseed.org"):
        with patch.object(
            api.APISettings, "max_user_signups", 3
        ):  # Limit of 3, currently have 6
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = (
                    mock_client_class.return_value.__aenter__.return_value
                )
                # Mock existing user logging back in
                mock_response = mock_rw_api_response("Test User")
                mock_response.json_data = {
                    "id": "existing-user",
                    "name": "Existing User",
                    "email": "existing@developmentseed.org",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "updatedAt": "2024-01-01T00:00:00Z",
                }
                mock_client.get.return_value = mock_response

                response = await client.get(
                    "/api/auth/me",
                    headers={"Authorization": "Bearer test-token"},
                )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["id"] == "existing-user"


@pytest.mark.asyncio
async def test_authentication_priority_order(client):
    """Test that authentication priority is: email whitelist > domain whitelist > public signup settings."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm, WhitelistedUserOrm
    from tests.conftest import async_session_maker

    # Pre-populate to reach signup limit
    async with async_session_maker() as session:
        for i in range(2):
            user = UserOrm(
                id=f"existing-{i}", name=f"User {i}", email=f"user{i}@test.com"
            )
            session.add(user)
        # Add email to whitelist but not domain
        whitelisted = WhitelistedUserOrm(email="priority@blocked.com")
        session.add(whitelisted)
        await session.commit()

    # Test: Email whitelist beats blocked domain + signup limit + disabled public
    with domain_allowlist(
        "developmentseed.org,wri.org"
    ):  # blocked.com not in list
        with patch.object(api.APISettings, "allow_public_signups", False):
            with patch.object(
                api.APISettings, "max_user_signups", 2
            ):  # At limit
                with patch("httpx.AsyncClient") as mock_client_class:
                    mock_client = (
                        mock_client_class.return_value.__aenter__.return_value
                    )
                    mock_response = mock_rw_api_response("Test User")
                    mock_response.json_data = {
                        "id": "priority-test",
                        "name": "Priority User",
                        "email": "priority@blocked.com",  # Not in domain list but in email whitelist
                        "createdAt": "2024-01-01T00:00:00Z",
                        "updatedAt": "2024-01-01T00:00:00Z",
                    }
                    mock_client.get.return_value = mock_response

                    response = await client.get(
                        "/api/auth/me",
                        headers={"Authorization": "Bearer test-token"},
                    )

                assert (
                    response.status_code == 200
                )  # Should succeed due to email whitelist
                user_data = response.json()
                assert user_data["email"] == "priority@blocked.com"


@pytest.mark.asyncio
async def test_metadata_signup_open_when_under_limit(client):
    """Test that metadata shows is_signup_open as True when under user limit."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm
    from tests.conftest import async_session_maker

    # Pre-populate with users below limit
    async with async_session_maker() as session:
        for i in range(2):
            user = UserOrm(
                id=f"user-{i}", name=f"User {i}", email=f"user{i}@test.com"
            )
            session.add(user)
        await session.commit()

    with patch.object(api.APISettings, "allow_public_signups", True):
        with patch.object(
            api.APISettings, "max_user_signups", 5
        ):  # Limit of 5, have 2
            response = await client.get("/api/metadata")

            assert response.status_code == 200
            metadata = response.json()
            assert metadata["is_signup_open"] is True


@pytest.mark.asyncio
async def test_metadata_signup_closed_when_at_limit(client):
    """Test that metadata shows is_signup_open as False when at user limit."""
    from unittest.mock import patch

    from src.api.data_models import UserOrm
    from tests.conftest import async_session_maker

    # Pre-populate to reach limit
    async with async_session_maker() as session:
        for i in range(3):
            user = UserOrm(
                id=f"user-{i}", name=f"User {i}", email=f"user{i}@test.com"
            )
            session.add(user)
        await session.commit()

    with patch.object(api.APISettings, "allow_public_signups", True):
        with patch.object(
            api.APISettings, "max_user_signups", 3
        ):  # Limit of 3, have 3
            response = await client.get("/api/metadata")

            assert response.status_code == 200
            metadata = response.json()
            assert metadata["is_signup_open"] is False


@pytest.mark.asyncio
async def test_metadata_signup_closed_when_public_disabled(client):
    """Test that metadata shows is_signup_open as False when public signups disabled."""
    from unittest.mock import patch

    with patch.object(api.APISettings, "allow_public_signups", False):
        with patch.object(
            api.APISettings, "max_user_signups", 100
        ):  # High limit
            response = await client.get("/api/metadata")

            assert response.status_code == 200
            metadata = response.json()
            assert metadata["is_signup_open"] is False


@pytest.mark.asyncio
async def test_metadata_signup_open_unlimited_users(client):
    """Test that metadata shows is_signup_open as True when user limit is unlimited."""
    from unittest.mock import patch

    with patch.object(api.APISettings, "allow_public_signups", True):
        with patch.object(
            api.APISettings, "max_user_signups", -1
        ):  # Unlimited
            response = await client.get("/api/metadata")

            assert response.status_code == 200
            metadata = response.json()
            assert metadata["is_signup_open"] is True
