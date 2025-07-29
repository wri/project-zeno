"""Tests for anonymous user access and quota enforcement."""
import pytest
from unittest.mock import patch
from src.utils.config import APISettings


@pytest.fixture
def anonymous_client(client):
    """Client without authentication headers."""
    return client


class TestAnonymousUserAccess:
    """Test anonymous user access to various endpoints."""
    
    def test_anonymous_user_can_access_chat_endpoint(self, anonymous_client):
        """Test that anonymous users can access the /api/chat endpoint."""
        chat_request = {
            "query": "Hello, world!",
            "thread_id": "test-thread-123"
        }
        
        # Mock the stream_chat function to avoid actual LLM calls
        with patch('src.api.app.stream_chat') as mock_stream:
            mock_stream.return_value = iter([b'{"response": "Hello!"}\\n'])
            
            response = anonymous_client.post("/api/chat", json=chat_request)
            
            # Should succeed for anonymous users
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/x-ndjson"

    def test_anonymous_user_cannot_access_protected_endpoints(self, anonymous_client):
        """Test that anonymous users cannot access protected endpoints."""
        protected_endpoints = [
            ("/api/auth/me", "GET"),
            ("/api/threads", "GET"), 
            ("/api/custom_areas/", "GET"),
            ("/api/custom_areas/", "POST")
        ]
        
        for endpoint, method in protected_endpoints:
            if method == "GET":
                response = anonymous_client.get(endpoint)
            elif method == "POST":
                response = anonymous_client.post(endpoint, json={})
            
            # Should return 422 (validation error) for missing auth
            assert response.status_code == 422
            assert "Authorization header is required" in response.json()["detail"]

    def test_quota_disabled_allows_chat_access(self, anonymous_client):
        """Test that disabling quotas allows unlimited chat access."""
        # Disable quota checking
        original_setting = APISettings.enable_quota_checking
        APISettings.enable_quota_checking = False
        
        try:
            chat_request = {
                "query": "Test message",
                "thread_id": "test-thread-123"
            }
            
            with patch('src.api.app.stream_chat') as mock_stream:
                mock_stream.return_value = iter([b'{"response": "OK"}\\n'])
                
                response = anonymous_client.post("/api/chat", json=chat_request)
                
                assert response.status_code == 200                
        finally:
            APISettings.enable_quota_checking = original_setting

    def test_anonymous_thread_continuity_via_thread_id(self, anonymous_client):
        """Test that anonymous users can maintain conversation continuity via thread_id."""
        thread_id = "continuous-thread-456"
        
        with patch('src.api.app.stream_chat') as mock_stream:
            mock_stream.return_value = iter([b'{"response": "OK"}\\n'])
            
            # First message
            response1 = anonymous_client.post("/api/chat", json={
                "query": "First message",
                "thread_id": thread_id
            })
            assert response1.status_code == 200
            
            # Second message with same thread_id
            response2 = anonymous_client.post("/api/chat", json={
                "query": "Second message", 
                "thread_id": thread_id
            })
            assert response2.status_code == 200
            
            # Verify stream_chat was called with correct thread_id both times
            calls = mock_stream.call_args_list
            assert len(calls) == 2
            assert calls[0][1]['thread_id'] == thread_id
            assert calls[1][1]['thread_id'] == thread_id