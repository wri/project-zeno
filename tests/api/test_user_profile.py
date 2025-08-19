"""Tests for user profile API functionality."""

import pytest

from src.user_profile_configs.countries import COUNTRIES
from src.user_profile_configs.gis_expertise import GIS_EXPERTISE_LEVELS
from src.user_profile_configs.languages import LANGUAGES
from src.user_profile_configs.sectors import SECTOR_ROLES, SECTORS


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

        # Verify data matches our configs
        assert data["sectors"] == SECTORS
        assert data["sector_roles"] == SECTOR_ROLES
        assert data["countries"] == COUNTRIES
        assert data["languages"] == LANGUAGES
        assert data["gis_expertise_levels"] == GIS_EXPERTISE_LEVELS

    @pytest.mark.asyncio
    async def test_profile_config_no_auth_required(self, client):
        """Test that profile config endpoint doesn't require authentication."""
        response = await client.get("/api/profile/config")
        assert response.status_code == 200


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
    async def test_update_profile_success_detailed_fields(
        self, client, user, auth_override
    ):
        """Test successful profile update with detailed fields."""
        auth_override(user.id)

        update_data = {
            "sector_code": self.valid_sector,
            "role_code": self.valid_role,
            "job_title": "Senior Analyst",
            "company_organization": "Environmental Institute",
            "country_code": self.valid_country,
            "preferred_language_code": self.valid_language,
            "gis_expertise_level": self.valid_expertise,
            "areas_of_interest": "Deforestation, Biodiversity, Climate Change",
        }

        response = await client.patch("/api/auth/profile", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["sectorCode"] == self.valid_sector
        assert data["roleCode"] == self.valid_role
        assert data["jobTitle"] == "Senior Analyst"
        assert data["companyOrganization"] == "Environmental Institute"
        assert data["countryCode"] == self.valid_country
        assert data["preferredLanguageCode"] == self.valid_language
        assert data["gisExpertiseLevel"] == self.valid_expertise
        assert (
            data["areasOfInterest"]
            == "Deforestation, Biodiversity, Climate Change"
        )

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
