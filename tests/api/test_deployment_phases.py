"""Tests for the 4-phase deployment rollout configuration."""

from unittest.mock import patch

import pytest

from src.utils.config import APISettings


class TestDeploymentPhases:
    """Test different deployment phase configurations."""

    @pytest.mark.asyncio
    async def test_phase_1_whitelisted_only(self, anonymous_client, client, auth_override):
        """Test Phase 1: Whitelisted users only configuration."""
        # Set Phase 1 configuration
        original_public_signups = APISettings.allow_public_signups
        original_anonymous_chat = APISettings.allow_anonymous_chat
        original_max_signups = APISettings.max_user_signups

        APISettings.allow_public_signups = False
        APISettings.allow_anonymous_chat = False
        APISettings.max_user_signups = -1

        try:
            chat_request = {
                "query": "Hello, world!",
                "thread_id": "test-thread-123",
            }

            # Anonymous users should be blocked
            response = await anonymous_client.post("/api/chat", json=chat_request)
            assert response.status_code == 401
            assert "Anonymous chat access is disabled" in response.json()["detail"]

            # Authenticated users should work
            auth_override("test-user-wri")
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])
                response = await client.post("/api/chat", json=chat_request)
                assert response.status_code == 200

        finally:
            APISettings.allow_public_signups = original_public_signups
            APISettings.allow_anonymous_chat = original_anonymous_chat
            APISettings.max_user_signups = original_max_signups

    @pytest.mark.asyncio
    async def test_phase_2_public_with_limits(self, anonymous_client, client, auth_override):
        """Test Phase 2: Public signups with limits configuration."""
        # Set Phase 2 configuration
        original_public_signups = APISettings.allow_public_signups
        original_anonymous_chat = APISettings.allow_anonymous_chat
        original_max_signups = APISettings.max_user_signups

        APISettings.allow_public_signups = True
        APISettings.allow_anonymous_chat = False
        APISettings.max_user_signups = 1000

        try:
            chat_request = {
                "query": "Hello, world!",
                "thread_id": "test-thread-123",
            }

            # Anonymous users should still be blocked
            response = await anonymous_client.post("/api/chat", json=chat_request)
            assert response.status_code == 401
            assert "Anonymous chat access is disabled" in response.json()["detail"]

            # Authenticated users should work
            auth_override("test-user-wri")
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])
                response = await client.post("/api/chat", json=chat_request)
                assert response.status_code == 200

        finally:
            APISettings.allow_public_signups = original_public_signups
            APISettings.allow_anonymous_chat = original_anonymous_chat
            APISettings.max_user_signups = original_max_signups

    @pytest.mark.asyncio
    async def test_phase_3_fully_public_with_login(self, anonymous_client, client, auth_override):
        """Test Phase 3: Fully public with required login configuration."""
        # Set Phase 3 configuration
        original_public_signups = APISettings.allow_public_signups
        original_anonymous_chat = APISettings.allow_anonymous_chat
        original_max_signups = APISettings.max_user_signups

        APISettings.allow_public_signups = True
        APISettings.allow_anonymous_chat = False
        APISettings.max_user_signups = -1

        try:
            chat_request = {
                "query": "Hello, world!",
                "thread_id": "test-thread-123",
            }

            # Anonymous users should still be blocked
            response = await anonymous_client.post("/api/chat", json=chat_request)
            assert response.status_code == 401
            assert "Anonymous chat access is disabled" in response.json()["detail"]

            # Authenticated users should work
            auth_override("test-user-wri")
            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])
                response = await client.post("/api/chat", json=chat_request)
                assert response.status_code == 200

        finally:
            APISettings.allow_public_signups = original_public_signups
            APISettings.allow_anonymous_chat = original_anonymous_chat
            APISettings.max_user_signups = original_max_signups

    @pytest.mark.asyncio
    async def test_phase_4_anonymous_allowed(self, anonymous_client, client, auth_override):
        """Test Phase 4: Anonymous access allowed configuration."""
        # Set Phase 4 configuration
        original_public_signups = APISettings.allow_public_signups
        original_anonymous_chat = APISettings.allow_anonymous_chat
        original_max_signups = APISettings.max_user_signups

        APISettings.allow_public_signups = True
        APISettings.allow_anonymous_chat = True
        APISettings.max_user_signups = -1

        try:
            chat_request = {
                "query": "Hello, world!",
                "thread_id": "test-thread-123",
            }

            with patch("src.api.app.stream_chat") as mock_stream:
                mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])

                # Anonymous users should now work
                response = await anonymous_client.post("/api/chat", json=chat_request)
                assert response.status_code == 200

                # Authenticated users should still work
                auth_override("test-user-wri")
                response = await client.post("/api/chat", json=chat_request)
                assert response.status_code == 200

        finally:
            APISettings.allow_public_signups = original_public_signups
            APISettings.allow_anonymous_chat = original_anonymous_chat
            APISettings.max_user_signups = original_max_signups

    @pytest.mark.asyncio
    async def test_metadata_endpoint_reflects_configuration(self, client):
        """Test that /api/metadata correctly reflects configuration status."""
        original_public_signups = APISettings.allow_public_signups
        original_anonymous_chat = APISettings.allow_anonymous_chat
        original_max_signups = APISettings.max_user_signups

        try:
            # Test Phase 1 (signups disabled, anonymous disabled)
            APISettings.allow_public_signups = False
            APISettings.allow_anonymous_chat = False
            response = await client.get("/api/metadata")
            assert response.status_code == 200
            data = response.json()
            assert data["is_signup_open"] is False
            assert data["allow_anonymous_chat"] is False

            # Test Phase 4 (signups enabled, anonymous enabled)
            APISettings.allow_public_signups = True
            APISettings.allow_anonymous_chat = True
            APISettings.max_user_signups = -1
            response = await client.get("/api/metadata")
            assert response.status_code == 200
            data = response.json()
            assert data["is_signup_open"] is True
            assert data["allow_anonymous_chat"] is True

        finally:
            APISettings.allow_public_signups = original_public_signups
            APISettings.allow_anonymous_chat = original_anonymous_chat
            APISettings.max_user_signups = original_max_signups