"""Tests for user profile API functionality."""

import pytest

from src.api.user_profile_configs.countries import COUNTRIES
from src.api.user_profile_configs.gis_expertise import GIS_EXPERTISE_LEVELS
from src.api.user_profile_configs.languages import LANGUAGES
from src.api.user_profile_configs.sectors import SECTOR_ROLES, SECTORS
from src.api.user_profile_configs.topics import TOPICS


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
