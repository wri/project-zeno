"""Tests for user profile API functionality."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.api.auth.dependencies import _user_info_cache
from src.api.cli import create_api_key, create_machine_user
from src.api.schemas import TERMS_VERSION_MAX_LENGTH
from src.api.user_profile_configs.countries import COUNTRIES
from src.api.user_profile_configs.gis_expertise import GIS_EXPERTISE_LEVELS
from src.api.user_profile_configs.languages import LANGUAGES
from src.api.user_profile_configs.sectors import SECTOR_ROLES, SECTORS
from src.api.user_profile_configs.topics import TOPICS
from tests.api.mock import (
    MockResponse,
    mock_rw_api_response,
    mock_rw_profile_response,
)
from tests.conftest import async_session_maker


class TestProfileConfigAPI:
    """Test the profile configuration API endpoint."""

    @pytest.mark.asyncio
    async def test_get_profile_config(self, client):
        """Test GET /api/profile/config returns all configuration options."""
        response = await client.get("/api/profile/config")

        assert response.status_code == 200
        data = response.json()

        # Verify all config sections are present and populated
        assert "sectors" in data and len(data["sectors"]) > 0
        assert "sector_roles" in data and len(data["sector_roles"]) > 0
        assert "countries" in data and len(data["countries"]) > 0
        assert "languages" in data and len(data["languages"]) > 0
        assert (
            "gis_expertise_levels" in data
            and len(data["gis_expertise_levels"]) > 0
        )
        assert "topics" in data and len(data["topics"]) > 0

        # Verify data matches our configs
        assert data["sectors"] == SECTORS
        assert data["sector_roles"] == SECTOR_ROLES
        assert data["countries"] == COUNTRIES
        assert data["languages"] == LANGUAGES
        assert data["gis_expertise_levels"] == GIS_EXPERTISE_LEVELS
        assert data["topics"] == TOPICS


class TestUserProfileAPI:
    """Test the user profile update API endpoint."""

    def setup_method(self):
        """Set up test data."""
        # Get valid values from configs for testing
        self.valid_sector = next(iter(SECTORS.keys()))
        self.valid_role = next(iter(SECTOR_ROLES[self.valid_sector].keys()))
        self.valid_country = next(iter(COUNTRIES.keys()))
        self.valid_language = next(iter(LANGUAGES.keys()))
        self.valid_expertise = next(iter(GIS_EXPERTISE_LEVELS.keys()))
        self.valid_topics = list(TOPICS.keys())[
            :2
        ]  # Get first 2 topics for testing

    @pytest.mark.asyncio
    async def test_update_profile_requires_auth(self, client):
        """Test PATCH /api/auth/profile requires authentication."""
        response = await client.patch(
            "/api/auth/profile", json={"first_name": "John"}
        )
        assert response.status_code == 401
        assert "Missing Bearer token" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_profile_success_basic_fields(
        self, client, user, auth_override
    ):
        """Test successful profile update with basic fields."""
        auth_override(user.id)

        update_data = {
            "first_name": "John",
            "last_name": "Doe",
            "profile_description": "Forest researcher interested in conservation",
        }

        response = await client.patch("/api/auth/profile", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["firstName"] == "John"
        assert data["lastName"] == "Doe"
        assert (
            data["profileDescription"]
            == "Forest researcher interested in conservation"
        )
        assert data["id"] == user.id
        assert data["name"] == user.name  # Original fields preserved

    @pytest.mark.asyncio
    async def test_update_profile_partial_update(
        self, client, user, auth_override
    ):
        """Test partial profile updates only change specified fields."""
        auth_override(user.id)

        # First update
        response = await client.patch(
            "/api/auth/profile",
            json={"first_name": "John", "job_title": "Analyst"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["firstName"] == "John"
        assert data["jobTitle"] == "Analyst"

        # Partial update - should preserve previous fields
        response = await client.patch(
            "/api/auth/profile", json={"last_name": "Doe"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["firstName"] == "John"  # Preserved
        assert data["lastName"] == "Doe"  # New
        assert data["jobTitle"] == "Analyst"  # Preserved

    @pytest.mark.asyncio
    async def test_update_profile_empty_update(
        self, client, user, auth_override
    ):
        """Test empty profile update doesn't break anything."""
        auth_override(user.id)

        response = await client.patch("/api/auth/profile", json={})
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == user.id
        assert data["name"] == user.name

    @pytest.mark.asyncio
    async def test_update_profile_validation_errors(
        self, client, user, auth_override
    ):
        """Test validation errors for invalid field values."""
        auth_override(user.id)

        # Test invalid sector
        response = await client.patch(
            "/api/auth/profile", json={"sector_code": "invalid_sector"}
        )
        assert response.status_code == 422
        assert "Invalid sector code" in str(response.json())

        # Test invalid country
        response = await client.patch(
            "/api/auth/profile", json={"country_code": "XX"}
        )
        assert response.status_code == 422
        assert "Invalid country code" in str(response.json())

        # Test invalid language
        response = await client.patch(
            "/api/auth/profile", json={"preferred_language_code": "xx"}
        )
        assert response.status_code == 422
        assert "Invalid language code" in str(response.json())

        # Test invalid expertise level
        response = await client.patch(
            "/api/auth/profile", json={"gis_expertise_level": "invalid"}
        )
        assert response.status_code == 422
        assert "Invalid GIS expertise level" in str(response.json())

    @pytest.mark.asyncio
    async def test_update_profile_new_fields(
        self, client, user, auth_override
    ):
        """Test updating the new profile fields: topics, receive_news_emails, help_test_features."""
        auth_override(user.id)

        update_data = {
            "topics": self.valid_topics,
            "receive_news_emails": True,
            "help_test_features": True,
        }

        response = await client.patch("/api/auth/profile", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["topics"] == self.valid_topics
        assert data["receiveNewsEmails"]
        assert data["helpTestFeatures"]

    @pytest.mark.asyncio
    async def test_update_profile_topics_validation(
        self, client, user, auth_override
    ):
        """Test topics field validation."""
        auth_override(user.id)

        # Test invalid topic
        response = await client.patch(
            "/api/auth/profile", json={"topics": ["invalid_topic"]}
        )
        assert response.status_code == 422
        assert "Invalid topic" in str(response.json())

        # Test non-list topics
        response = await client.patch(
            "/api/auth/profile", json={"topics": "not_a_list"}
        )
        assert response.status_code == 422
        assert "Input should be a valid list" in str(response.json())

        # Test valid topics
        response = await client.patch(
            "/api/auth/profile", json={"topics": self.valid_topics}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["topics"] == self.valid_topics

    @pytest.mark.asyncio
    async def test_update_profile_topics_empty_list(
        self, client, user, auth_override
    ):
        """Test topics can be set to empty list."""
        auth_override(user.id)

        # First set some topics
        response = await client.patch(
            "/api/auth/profile", json={"topics": self.valid_topics}
        )
        assert response.status_code == 200
        assert response.json()["topics"] == self.valid_topics

        # Then set to empty list
        response = await client.patch("/api/auth/profile", json={"topics": []})
        assert response.status_code == 200
        assert response.json()["topics"] == []

    @pytest.mark.asyncio
    async def test_update_profile_topics_null(
        self, client, user, auth_override
    ):
        """Test topics can be set to null."""
        auth_override(user.id)

        # First set some topics
        response = await client.patch(
            "/api/auth/profile", json={"topics": self.valid_topics}
        )
        assert response.status_code == 200
        assert response.json()["topics"] == self.valid_topics

        # Then set to null
        response = await client.patch(
            "/api/auth/profile", json={"topics": None}
        )
        assert response.status_code == 200
        assert response.json()["topics"] is None

    @pytest.mark.asyncio
    async def test_update_profile_boolean_fields(
        self, client, user, auth_override
    ):
        """Test boolean fields can be set to true/false."""
        auth_override(user.id)

        # Test setting to True
        response = await client.patch(
            "/api/auth/profile",
            json={"receive_news_emails": True, "help_test_features": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["receiveNewsEmails"]
        assert data["helpTestFeatures"]

        # Test setting to False
        response = await client.patch(
            "/api/auth/profile",
            json={"receive_news_emails": False, "help_test_features": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert not data["receiveNewsEmails"]
        assert not data["helpTestFeatures"]

    @pytest.mark.asyncio
    async def test_user_auto_creation(self, client, auth_override):
        """Test that users are auto-created on first profile update."""
        # Use non-existent user (will be auto-created by require_auth)
        auth_override("new-user-id")

        response = await client.patch(
            "/api/auth/profile", json={"first_name": "Alice"}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["firstName"] == "Alice"
        assert data["id"] == "new-user-id"

    @pytest.mark.asyncio
    async def test_profile_fields_roundtrip_auth_me(
        self, client, user, auth_override
    ):
        """Test that profile fields saved via PATCH are retrieved via GET /api/auth/me."""
        auth_override(user.id)

        # Update profile with all field types
        profile_data = {
            "first_name": "Jane",
            "last_name": "Smith",
            "profile_description": "Forest conservation researcher",
            "sector_code": self.valid_sector,
            "role_code": self.valid_role,
            "job_title": "Senior Research Scientist",
            "company_organization": "Global Forest Institute",
            "country_code": self.valid_country,
            "preferred_language_code": self.valid_language,
            "gis_expertise_level": self.valid_expertise,
            "areas_of_interest": "Biodiversity monitoring, Climate change impact",
        }

        # Save profile via PATCH
        response = await client.patch("/api/auth/profile", json=profile_data)
        assert response.status_code == 200

        # Retrieve profile via GET /api/auth/me
        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200

        # Verify all profile fields are correctly returned
        data = response.json()
        assert data["firstName"] == "Jane"
        assert data["lastName"] == "Smith"
        assert data["profileDescription"] == "Forest conservation researcher"
        assert data["sectorCode"] == self.valid_sector
        assert data["roleCode"] == self.valid_role
        assert data["jobTitle"] == "Senior Research Scientist"
        assert data["companyOrganization"] == "Global Forest Institute"
        assert data["countryCode"] == self.valid_country
        assert data["preferredLanguageCode"] == self.valid_language
        assert data["gisExpertiseLevel"] == self.valid_expertise
        assert (
            data["areasOfInterest"]
            == "Biodiversity monitoring, Climate change impact"
        )

        # Verify core fields are still present
        assert data["id"] == user.id
        assert data["name"] == user.name
        assert data["email"] == user.email

    @pytest.mark.asyncio
    async def test_partial_update_roundtrip_auth_me(
        self, client, user, auth_override
    ):
        """Test that partial profile updates are correctly reflected in GET /api/auth/me."""
        auth_override(user.id)

        # First, set some initial profile data
        initial_data = {
            "first_name": "John",
            "sector_code": self.valid_sector,
            "job_title": "Analyst",
        }
        response = await client.patch("/api/auth/profile", json=initial_data)
        assert response.status_code == 200

        # Then update only some fields
        partial_update = {
            "last_name": "Doe",
            "profile_description": "Updated description",
        }
        response = await client.patch("/api/auth/profile", json=partial_update)
        assert response.status_code == 200

        # Verify all fields via GET /api/auth/me
        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200

        data = response.json()
        # Previously set fields should remain
        assert data["firstName"] == "John"
        assert data["sectorCode"] == self.valid_sector
        assert data["jobTitle"] == "Analyst"
        # Newly updated fields should be set
        assert data["lastName"] == "Doe"
        assert data["profileDescription"] == "Updated description"
        # Unset fields should be null
        assert data["countryCode"] is None
        assert data["areasOfInterest"] is None

    @pytest.mark.asyncio
    async def test_profile_fields_null_by_default_in_auth_me(
        self, client, user, auth_override
    ):
        """Test that profile fields are null by default in GET /api/auth/me for existing users."""
        auth_override(user.id)

        # Get user profile without any updates
        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200

        data = response.json()

        # Core fields should be present
        assert data["id"] == user.id
        assert data["name"] == user.name
        assert data["email"] == user.email

        # All profile fields should be null/None for new users
        assert data["firstName"] is None
        assert data["lastName"] is None
        assert data["profileDescription"] is None
        assert data["sectorCode"] is None
        assert data["roleCode"] is None
        assert data["jobTitle"] is None
        assert data["companyOrganization"] is None
        assert data["countryCode"] is None
        assert data["preferredLanguageCode"] is None
        assert data["gisExpertiseLevel"] is None
        assert data["areasOfInterest"] is None
        assert data["hasProfile"] is False

    @pytest.mark.asyncio
    async def test_profile_fields_persist_across_sessions(
        self, client, user, auth_override
    ):
        """Test that profile fields persist across different authentication sessions."""
        auth_override(user.id)

        # Set profile data
        profile_data = {
            "first_name": "Persistent",
            "job_title": "Data Scientist",
        }
        response = await client.patch("/api/auth/profile", json=profile_data)
        assert response.status_code == 200

        # Simulate new session by making multiple auth/me requests
        for i in range(3):
            response = await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer test-token"}
            )
            assert response.status_code == 200

            data = response.json()
            assert data["firstName"] == "Persistent"
            assert data["jobTitle"] == "Data Scientist"
            assert data["id"] == user.id
            assert data["hasProfile"] is False

    @pytest.mark.asyncio
    async def test_has_profile_field_update(self, client, user, auth_override):
        """Test that has_profile field can be updated independently."""
        auth_override(user.id)

        # Initially has_profile should be False
        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200
        assert response.json()["hasProfile"] is False

        # Update has_profile to True
        response = await client.patch(
            "/api/auth/profile", json={"has_profile": True}
        )
        assert response.status_code == 200
        assert response.json()["hasProfile"] is True

        # Verify it persists in subsequent requests
        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200
        assert response.json()["hasProfile"] is True

        # Update back to False
        response = await client.patch(
            "/api/auth/profile", json={"has_profile": False}
        )
        assert response.status_code == 200
        assert response.json()["hasProfile"] is False

    @pytest.mark.asyncio
    async def test_has_profile_with_other_fields(
        self, client, user, auth_override
    ):
        """Test that has_profile can be updated alongside other profile fields."""
        auth_override(user.id)

        # Update multiple fields including has_profile
        update_data = {
            "first_name": "Jane",
            "last_name": "Doe",
            "has_profile": True,
            "job_title": "Researcher",
        }

        response = await client.patch("/api/auth/profile", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["firstName"] == "Jane"
        assert data["lastName"] == "Doe"
        assert data["hasProfile"] is True
        assert data["jobTitle"] == "Researcher"

    @pytest.mark.asyncio
    async def test_new_profile_fields_in_auth_me(
        self, client, user, auth_override
    ):
        """Test that topics, receive_news_emails, and help_test_features appear in /auth/me after being set."""
        auth_override(user.id)

        # Set the new profile fields
        update_data = {
            "topics": self.valid_topics,
            "receive_news_emails": True,
            "help_test_features": False,
        }

        # Update profile via PATCH
        response = await client.patch("/api/auth/profile", json=update_data)
        assert response.status_code == 200

        # Verify the fields are returned in the PATCH response
        patch_data = response.json()
        assert patch_data["topics"] == self.valid_topics
        assert patch_data["receiveNewsEmails"] is True
        assert patch_data["helpTestFeatures"] is False

        # Verify the fields are also returned in /auth/me
        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200

        auth_me_data = response.json()
        assert auth_me_data["topics"] == self.valid_topics
        assert auth_me_data["receiveNewsEmails"] is True
        assert auth_me_data["helpTestFeatures"] is False

        # Verify other profile fields are still present
        assert auth_me_data["id"] == user.id
        assert auth_me_data["name"] == user.name
        assert auth_me_data["email"] == user.email

    @pytest.mark.asyncio
    async def test_new_profile_fields_null_by_default_in_auth_me(
        self, client, user, auth_override
    ):
        """Test that new profile fields are null/false by default in /auth/me."""
        auth_override(user.id)

        # Get user profile without any updates
        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200

        data = response.json()

        # New fields should have their default values
        assert data["topics"] is None
        assert data["receiveNewsEmails"] is False
        assert data["helpTestFeatures"] is False


class TestTermsAcceptance:
    """Terms acceptance is exposed on the user and recorded by PATCH."""

    @pytest.mark.asyncio
    async def test_terms_fields_null_by_default_in_auth_me(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        response = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["termsAcceptedAt"] is None
        assert data["termsVersion"] is None
        assert data["termsAccepted"] is False

    @pytest.mark.asyncio
    async def test_profile_update_response_includes_terms_fields(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        response = await client.patch(
            "/api/auth/profile", json={"first_name": "Ada"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["termsAcceptedAt"] is None
        assert data["termsVersion"] is None
        assert data["termsAccepted"] is False

    @pytest.mark.asyncio
    async def test_accepting_terms_marks_terms_accepted(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        response = await client.patch(
            "/api/auth/profile", json={"terms_version": "2026-09-30"}
        )

        assert response.json()["termsAccepted"] is True
        me = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert me.json()["termsAccepted"] is True

    @pytest.mark.asyncio
    async def test_completed_legacy_profile_counts_as_terms_accepted(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        response = await client.patch(
            "/api/auth/profile", json={"has_profile": True}
        )

        assert response.json()["termsAccepted"] is True
        assert response.json()["termsAcceptedAt"] is None
        me = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert me.json()["termsAccepted"] is True
        assert me.json()["termsAcceptedAt"] is None

    @pytest.mark.asyncio
    async def test_accepting_terms_records_version_and_server_time(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        before = datetime.now(timezone.utc)
        response = await client.patch(
            "/api/auth/profile", json={"terms_version": "2026-09-30"}
        )
        after = datetime.now(timezone.utc)

        assert response.status_code == 200
        data = response.json()
        assert data["termsVersion"] == "2026-09-30"
        accepted_at = datetime.fromisoformat(data["termsAcceptedAt"])
        assert accepted_at.tzinfo is not None
        assert before <= accepted_at <= after

        me = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert me.json()["termsVersion"] == "2026-09-30"
        assert (
            datetime.fromisoformat(me.json()["termsAcceptedAt"]) == accepted_at
        )

    @pytest.mark.asyncio
    async def test_client_supplied_acceptance_time_is_ignored(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        before = datetime.now(timezone.utc)
        response = await client.patch(
            "/api/auth/profile",
            json={
                "terms_version": "2026-09-30",
                "terms_accepted_at": "2000-01-01T00:00:00Z",
            },
        )

        assert response.status_code == 200
        accepted_at = datetime.fromisoformat(
            response.json()["termsAcceptedAt"]
        )
        assert accepted_at >= before

    @pytest.mark.asyncio
    async def test_terms_acceptance_time_alone_is_not_accepted(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        response = await client.patch(
            "/api/auth/profile",
            json={"terms_accepted_at": "2000-01-01T00:00:00Z"},
        )

        assert response.status_code == 200
        assert response.json()["termsAcceptedAt"] is None
        assert response.json()["termsVersion"] is None

    @pytest.mark.asyncio
    async def test_terms_version_is_trimmed(self, client, user, auth_override):
        auth_override(user.id)

        response = await client.patch(
            "/api/auth/profile", json={"terms_version": "  2026-09-30 "}
        )

        assert response.status_code == 200
        assert response.json()["termsVersion"] == "2026-09-30"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "terms_version",
        ["", "   ", "x" * (TERMS_VERSION_MAX_LENGTH + 1), None],
        ids=["empty", "whitespace", "too-long", "null"],
    )
    async def test_invalid_terms_version_is_rejected(
        self, client, user, auth_override, terms_version
    ):
        auth_override(user.id)

        response = await client.patch(
            "/api/auth/profile", json={"terms_version": terms_version}
        )

        assert response.status_code == 422
        me = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer test-token"}
        )
        assert me.json()["termsVersion"] is None
        assert me.json()["termsAcceptedAt"] is None

    @pytest.mark.asyncio
    async def test_terms_version_at_max_length_is_accepted(
        self, client, user, auth_override
    ):
        auth_override(user.id)
        version = "v" * TERMS_VERSION_MAX_LENGTH

        response = await client.patch(
            "/api/auth/profile", json={"terms_version": version}
        )

        assert response.status_code == 200
        assert response.json()["termsVersion"] == version

    @pytest.mark.asyncio
    async def test_other_profile_updates_leave_acceptance_untouched(
        self, client, user, auth_override
    ):
        auth_override(user.id)
        accepted = await client.patch(
            "/api/auth/profile", json={"terms_version": "2026-09-30"}
        )

        response = await client.patch(
            "/api/auth/profile", json={"first_name": "Ada"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["firstName"] == "Ada"
        assert data["termsVersion"] == "2026-09-30"
        assert data["termsAcceptedAt"] == accepted.json()["termsAcceptedAt"]

    @pytest.mark.asyncio
    async def test_terms_can_be_accepted_with_other_profile_fields(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        response = await client.patch(
            "/api/auth/profile",
            json={"terms_version": "2026-09-30", "first_name": "Ada"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["firstName"] == "Ada"
        assert data["termsVersion"] == "2026-09-30"
        assert data["termsAcceptedAt"] is not None

    @pytest.mark.asyncio
    async def test_each_acceptance_restamps_the_time(
        self, client, user, auth_override
    ):
        auth_override(user.id)
        first = await client.patch(
            "/api/auth/profile", json={"terms_version": "2026-09-30"}
        )

        second = await client.patch(
            "/api/auth/profile", json={"terms_version": "2026-09-30"}
        )

        assert second.status_code == 200
        assert datetime.fromisoformat(
            second.json()["termsAcceptedAt"]
        ) > datetime.fromisoformat(first.json()["termsAcceptedAt"])


# What the gfw profile form saves on the RW user (see
# tests/unit/api/services/test_profile_prefill.py for the mapping cases).
MYGFW_ATTRIBUTES = {
    "firstName": "Ana",
    "lastName": "Silva",
    "email": "ana@example.org",
    "applicationData": {
        "gfw": {
            "country": "BRA",
            "sector": "Local NGO (national or subnational)",
            "company": "Instituto Floresta",
            "jobTitle": "GIS analyst",
            "interests": ["deforestation", "biodiversity"],
            "receive_updates": True,
            "preferred_language": "pt",
            "signUpForTesting": "true",
        }
    },
}

MYGFW_SUGGESTION = {
    "first_name": "Ana",
    "last_name": "Silva",
    "job_title": "GIS analyst",
    "company_organization": "Instituto Floresta",
    "sector_code": "local_ngo",
    "country_code": "BR",
    "preferred_language_code": "pt",
    "topics": ["combating_deforestation", "protecting_ecosystems"],
}

NOT_FOUND = {"found": False, "source": None, "suggestion": None}
RW_TOKEN = {"Authorization": "Bearer rw-token"}


async def _prefill(client, rw_response, headers=RW_TOKEN):
    """GET /api/auth/profile/prefill with Resource Watch mocked.

    ``rw_response`` is what RW's GET answers: a response, an exception to
    raise, or a function of the URL. Returns the API response and the mocked
    ``get`` so a test can inspect the RW calls.
    """
    with patch("httpx.AsyncClient") as mock_client_class:
        rw_get = mock_client_class.return_value.__aenter__.return_value.get
        if isinstance(rw_response, BaseException) or callable(rw_response):
            rw_get.side_effect = rw_response
        else:
            rw_get.return_value = rw_response
        response = await client.get(
            "/api/auth/profile/prefill", headers=headers
        )
    return response, rw_get


class TestProfilePrefillAPI:
    """GET /api/auth/profile/prefill suggests fields from MyGFW."""

    @pytest.mark.asyncio
    async def test_prefill_requires_auth(self, client):
        response = await client.get("/api/auth/profile/prefill")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_prefill_suggests_fields_from_mygfw_profile(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        response, rw_get = await _prefill(
            client, mock_rw_profile_response(user.id, MYGFW_ATTRIBUTES)
        )

        assert response.status_code == 200
        assert response.json() == {
            "found": True,
            "source": "gfw",
            "suggestion": MYGFW_SUGGESTION,
        }
        rw_get.assert_called_once()
        url = rw_get.call_args.args[0]
        headers = rw_get.call_args.kwargs["headers"]
        assert url == f"https://api.resourcewatch.org/v2/user/{user.id}"
        assert headers["Authorization"] == "Bearer rw-token"

    @pytest.mark.asyncio
    async def test_prefill_never_writes_the_profile(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        await _prefill(
            client, mock_rw_profile_response(user.id, MYGFW_ATTRIBUTES)
        )

        me = await client.get("/api/auth/me", headers=RW_TOKEN)
        assert me.json()["firstName"] is None
        assert me.json()["sectorCode"] is None
        assert me.json()["countryCode"] is None
        assert me.json()["topics"] is None

    @pytest.mark.asyncio
    async def test_prefill_without_mygfw_profile_is_not_found(
        self, client, user, auth_override
    ):
        auth_override(user.id)

        response, _ = await _prefill(
            client,
            MockResponse(
                {"errors": [{"status": 404, "detail": "User not found"}]},
                404,
            ),
        )

        assert response.status_code == 200
        assert response.json() == NOT_FOUND

    @pytest.mark.asyncio
    async def test_prefill_with_nothing_mappable_is_not_found(
        self, client, user, auth_override
    ):
        auth_override(user.id)
        attributes = {
            "email": "ana@example.org",
            "applicationData": {
                "gfw": {"sector": "Space agency", "receive_updates": True}
            },
        }

        response, _ = await _prefill(
            client, mock_rw_profile_response(user.id, attributes)
        )

        assert response.status_code == 200
        assert response.json() == NOT_FOUND

    @pytest.mark.asyncio
    async def test_prefill_body_without_data_attributes_is_not_found(
        self, client, user, auth_override
    ):
        # The RW shape comes from reading the gfw frontend, not from a live
        # response. A different shape must degrade to "nothing to prefill".
        auth_override(user.id)

        response, _ = await _prefill(
            client, MockResponse({"id": user.id, **MYGFW_ATTRIBUTES})
        )

        assert response.status_code == 200
        assert response.json() == NOT_FOUND

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 401, 403, 500, 503])
    async def test_prefill_fails_loudly_on_unexpected_rw_status(
        self, client, user, auth_override, status_code
    ):
        auth_override(user.id)

        response, _ = await _prefill(
            client, MockResponse({"errors": [{"detail": "nope"}]}, status_code)
        )

        assert response.status_code == 502
        assert "nope" not in response.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")],
        ids=["connect", "timeout"],
    )
    async def test_prefill_fails_loudly_when_rw_is_unreachable(
        self, client, user, auth_override, error
    ):
        auth_override(user.id)

        response, _ = await _prefill(client, error)

        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_prefill_fails_loudly_on_non_json_body(
        self, client, user, auth_override
    ):
        auth_override(user.id)
        not_json = MockResponse(None)
        not_json.json = MagicMock(side_effect=ValueError("not json"))

        response, _ = await _prefill(client, not_json)

        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_prefill_for_machine_user_never_calls_rw(self, client):
        async with async_session_maker() as session:
            machine = await create_machine_user(
                session, "prefill-bot", "prefill-bot@example.org"
            )
            token, _ = await create_api_key(session, machine.id, "test")

        response, rw_get = await _prefill(
            client,
            MockResponse({}),
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert response.json() == NOT_FOUND
        rw_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_prefill_through_real_rw_login(self, client):
        # No auth override: the same RW token validates the caller
        # (/auth/user/me) and then reads their MyGFW profile.
        _user_info_cache.clear()
        rw_user = mock_rw_api_response("Test User").json_data
        profile = mock_rw_profile_response(rw_user["id"], MYGFW_ATTRIBUTES)

        def route(url, **kwargs):
            if url.endswith("/auth/user/me"):
                return mock_rw_api_response("Test User")
            if url.endswith(f"/v2/user/{rw_user['id']}"):
                return profile
            raise AssertionError(f"Unexpected RW call: {url}")

        response, _ = await _prefill(client, route)
        _user_info_cache.clear()

        assert response.status_code == 200
        assert response.json()["found"] is True
        assert response.json()["suggestion"] == MYGFW_SUGGESTION


class TestProfileConfigsStructure:
    """Basic tests to ensure configuration files are properly structured."""

    def test_configs_exist_and_valid(self):
        """Test that all configuration dictionaries exist and are valid."""
        # Test sectors and roles
        assert isinstance(SECTORS, dict) and len(SECTORS) > 0
        assert isinstance(SECTOR_ROLES, dict) and len(SECTOR_ROLES) > 0

        # Test all sectors have roles
        for sector_code in SECTORS.keys():
            assert sector_code in SECTOR_ROLES
            assert isinstance(SECTOR_ROLES[sector_code], dict)
            assert len(SECTOR_ROLES[sector_code]) > 0

        # Test other configs
        assert isinstance(COUNTRIES, dict) and len(COUNTRIES) > 0
        assert isinstance(LANGUAGES, dict) and len(LANGUAGES) > 0
        assert (
            isinstance(GIS_EXPERTISE_LEVELS, dict)
            and len(GIS_EXPERTISE_LEVELS) > 0
        )
