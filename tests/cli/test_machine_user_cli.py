"""Comprehensive tests for machine user CLI functionality."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import bcrypt
import pytest
from click.testing import CliRunner

from src.api.data_models import UserOrm, UserType
from src.cli import (
    cli,
    create_api_key,
    create_machine_user,
    generate_api_key,
    list_api_keys,
    list_machine_users,
    revoke_api_key,
    rotate_api_key,
)

# Import the async_session_maker from conftest.py
from tests.conftest import async_session_maker


@pytest.fixture
def test_user_data():
    """Sample user data for testing."""
    return {
        "name": "Test Machine User",
        "email": "test@example.com",
        "description": "Test machine user for automated testing",
    }


class TestGenerateApiKey:
    """Test API key generation functionality."""

    def test_generate_api_key_format(self):
        """Test that generated API keys have the correct format."""
        full_token, prefix, token_hash = generate_api_key()

        # Check format: zeno-key:prefix:secret
        parts = full_token.split(":")
        assert len(parts) == 3
        assert parts[0] == "zeno-key"
        assert parts[1] == prefix
        assert len(prefix) == 8
        assert len(parts[2]) == 32  # 32-char hex secret

        # Verify hash can be used to validate the secret
        secret = parts[2]
        assert bcrypt.checkpw(secret.encode(), token_hash.encode())

    def test_generate_api_key_uniqueness(self):
        """Test that generated API keys are unique."""
        keys = [generate_api_key() for _ in range(10)]
        full_tokens = [k[0] for k in keys]
        prefixes = [k[1] for k in keys]

        # All tokens should be unique
        assert len(set(full_tokens)) == 10
        assert len(set(prefixes)) == 10


class TestMachineUserFunctions:
    """Test machine user management functions."""

    @pytest.mark.asyncio
    async def test_create_machine_user_success(self, test_user_data):
        """Test successful machine user creation."""
        async with async_session_maker() as session:
            user = await create_machine_user(
                session,
                test_user_data["name"],
                test_user_data["email"],
                test_user_data["description"],
            )

            assert user.name == test_user_data["name"]
            assert user.email == test_user_data["email"]
            assert user.machine_description == test_user_data["description"]
            assert user.user_type == UserType.MACHINE.value
            assert user.id.startswith("machine_")

    @pytest.mark.asyncio
    async def test_create_machine_user_duplicate_email(self, test_user_data):
        """Test that creating a user with duplicate email fails."""
        async with async_session_maker() as session:
            # Create first user
            await create_machine_user(
                session,
                test_user_data["name"],
                test_user_data["email"],
                test_user_data["description"],
            )

            # Try to create second user with same email
            with pytest.raises(ValueError, match="already exists"):
                await create_machine_user(
                    session,
                    "Another User",
                    test_user_data["email"],
                    "Different description",
                )

    @pytest.mark.asyncio
    async def test_create_api_key_success(self, test_user_data):
        """Test successful API key creation."""
        async with async_session_maker() as session:
            # Create machine user first
            user = await create_machine_user(
                session,
                test_user_data["name"],
                test_user_data["email"],
                test_user_data["description"],
            )

            # Create API key
            full_token, api_key = await create_api_key(
                session, user.id, "test-key"
            )

            assert api_key.user_id == user.id
            assert api_key.key_name == "test-key"
            assert api_key.is_active is True
            assert api_key.expires_at is None
            assert len(api_key.key_prefix) == 8

            # Verify token format
            parts = full_token.split(":")
            assert len(parts) == 3
            assert parts[0] == "zeno-key"
            assert parts[1] == api_key.key_prefix

    @pytest.mark.asyncio
    async def test_create_api_key_with_expiration(self, test_user_data):
        """Test API key creation with expiration date."""
        async with async_session_maker() as session:
            # Create machine user first
            user = await create_machine_user(
                session,
                test_user_data["name"],
                test_user_data["email"],
                test_user_data["description"],
            )

            # Create API key with expiration
            expires_at = datetime.now() + timedelta(days=30)
            full_token, api_key = await create_api_key(
                session, user.id, "test-key-expires", expires_at
            )

            assert api_key.expires_at is not None
            assert api_key.expires_at.date() == expires_at.date()

    @pytest.mark.asyncio
    async def test_create_api_key_invalid_user(self):
        """Test API key creation with invalid user ID."""
        async with async_session_maker() as session:
            with pytest.raises(ValueError, match="not found"):
                await create_api_key(session, "invalid_user_id", "test-key")

    @pytest.mark.asyncio
    async def test_create_api_key_non_machine_user(self):
        """Test API key creation with non-machine user."""
        async with async_session_maker() as session:
            # Create regular user
            regular_user = UserOrm(
                id="regular_user_123",
                name="Regular User",
                email="regular@example.com",
                user_type=UserType.REGULAR.value,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(regular_user)
            await session.commit()

            with pytest.raises(ValueError, match="not a machine user"):
                await create_api_key(session, regular_user.id, "test-key")

    @pytest.mark.asyncio
    async def test_list_machine_users(self, test_user_data):
        """Test listing machine users."""
        async with async_session_maker() as session:
            # Create multiple machine users
            user1 = await create_machine_user(
                session,
                test_user_data["name"],
                test_user_data["email"],
                test_user_data["description"],
            )
            user2 = await create_machine_user(
                session,
                "Another Machine User",
                "another@example.com",
                "Another description",
            )

            # Create regular user (should not appear in list)
            regular_user = UserOrm(
                id="regular_user_123",
                name="Regular User",
                email="regular@example.com",
                user_type=UserType.REGULAR.value,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(regular_user)
            await session.commit()

            # List machine users
            machine_users = await list_machine_users(session)

            assert len(machine_users) == 2
            user_ids = [u.id for u in machine_users]
            assert user1.id in user_ids
            assert user2.id in user_ids
            assert regular_user.id not in user_ids

    @pytest.mark.asyncio
    async def test_list_api_keys(self, test_user_data):
        """Test listing API keys for a user."""
        async with async_session_maker() as session:
            # Create machine user
            user = await create_machine_user(
                session,
                test_user_data["name"],
                test_user_data["email"],
                test_user_data["description"],
            )

            # Create multiple API keys
            full_token1, api_key1 = await create_api_key(
                session, user.id, "key1"
            )
            full_token2, api_key2 = await create_api_key(
                session, user.id, "key2"
            )

            # List API keys
            keys = await list_api_keys(session, user.id)

            assert len(keys) == 2
            key_names = [k.key_name for k in keys]
            assert "key1" in key_names
            assert "key2" in key_names

    @pytest.mark.asyncio
    async def test_rotate_api_key(self, test_user_data):
        """Test API key rotation."""
        async with async_session_maker() as session:
            # Create machine user and key
            user = await create_machine_user(
                session,
                test_user_data["name"],
                test_user_data["email"],
                test_user_data["description"],
            )
            old_token, old_key = await create_api_key(
                session, user.id, "test-key"
            )
            old_prefix = old_key.key_prefix
            old_hash = old_key.key_hash

            # Rotate the key
            new_token, rotated_key = await rotate_api_key(session, old_key.id)

            # Verify rotation
            assert rotated_key.id == old_key.id  # Same key record
            assert rotated_key.key_prefix == old_prefix  # Same prefix
            assert rotated_key.key_hash != old_hash  # Different hash
            assert new_token != old_token  # Different token
            assert rotated_key.updated_at > old_key.created_at

    @pytest.mark.asyncio
    async def test_revoke_api_key(self, test_user_data):
        """Test API key revocation."""
        async with async_session_maker() as session:
            # Create machine user and key
            user = await create_machine_user(
                session,
                test_user_data["name"],
                test_user_data["email"],
                test_user_data["description"],
            )
            full_token, api_key = await create_api_key(
                session, user.id, "test-key"
            )

            # Verify key is active
            assert api_key.is_active is True

            # Revoke the key
            revoked_key = await revoke_api_key(session, api_key.id)

            # Verify revocation
            assert revoked_key.id == api_key.id
            assert revoked_key.is_active is False
            assert revoked_key.updated_at > api_key.created_at


class TestCLICommands:
    """Test CLI command functionality."""

    def setup_method(self):
        """Set up test runner."""
        self.runner = CliRunner()

    @patch("src.cli.DatabaseManager")
    @patch("src.cli.create_machine_user")
    def test_create_machine_user_command(
        self, mock_create_user, mock_db_manager
    ):
        """Test create-machine-user CLI command."""
        # Mock database operations
        mock_session = AsyncMock()
        mock_db_manager.return_value.async_session.return_value.__aenter__.return_value = mock_session
        mock_db_manager.return_value.close = AsyncMock()

        # Mock created user
        mock_user = AsyncMock()
        mock_user.id = "machine_test123"
        mock_user.name = "Test User"
        mock_user.email = "test@example.com"
        mock_user.machine_description = "Test description"
        mock_user.created_at = datetime.now()
        mock_create_user.return_value = mock_user

        # Run command
        result = self.runner.invoke(
            cli,
            [
                "create-machine-user",
                "--name",
                "Test User",
                "--email",
                "test@example.com",
                "--description",
                "Test description",
            ],
        )

        assert result.exit_code == 0
        assert "✅ Created machine user:" in result.output
        assert "Test User" in result.output
        mock_create_user.assert_called_once()

    @patch("src.cli.DatabaseManager")
    @patch("src.cli.create_machine_user")
    @patch("src.cli.create_api_key")
    def test_create_machine_user_with_key(
        self, mock_create_key, mock_create_user, mock_db_manager
    ):
        """Test create-machine-user CLI command with --create-key flag."""
        # Mock database operations
        mock_session = AsyncMock()
        mock_db_manager.return_value.async_session.return_value.__aenter__.return_value = mock_session
        mock_db_manager.return_value.close = AsyncMock()

        # Mock created user
        mock_user = AsyncMock()
        mock_user.id = "machine_test123"
        mock_user.name = "Test User"
        mock_user.email = "test@example.com"
        mock_user.created_at = datetime.now()
        mock_create_user.return_value = mock_user

        # Mock created API key
        mock_key = AsyncMock()
        mock_key.id = "key_123"
        mock_key.key_name = "default"
        mock_key.key_prefix = "abc12345"
        mock_key.created_at = datetime.now()
        mock_create_key.return_value = (
            "zeno-key:abc12345:secret123",
            mock_key,
        )

        # Run command with --create-key
        result = self.runner.invoke(
            cli,
            [
                "create-machine-user",
                "--name",
                "Test User",
                "--email",
                "test@example.com",
                "--create-key",
            ],
        )

        assert result.exit_code == 0
        assert "✅ Created machine user:" in result.output
        assert "🔑 Creating initial API key..." in result.output
        assert "✅ Created API key:" in result.output
        assert "zeno-key:abc12345:secret123" in result.output
        mock_create_user.assert_called_once()
        mock_create_key.assert_called_once()

    @patch("src.cli.DatabaseManager")
    @patch("src.cli.list_machine_users")
    def test_list_machine_users_command(
        self, mock_list_users, mock_db_manager
    ):
        """Test list-machine-users CLI command."""
        # Mock database operations
        mock_session = AsyncMock()
        mock_db_manager.return_value.async_session.return_value.__aenter__.return_value = mock_session
        mock_db_manager.return_value.close = AsyncMock()

        # Mock users
        mock_user1 = AsyncMock()
        mock_user1.id = "machine_test123"
        mock_user1.name = "Test User 1"
        mock_user1.email = "test1@example.com"
        mock_user1.machine_description = "Description 1"
        mock_user1.created_at = datetime.now()

        mock_user2 = AsyncMock()
        mock_user2.id = "machine_test456"
        mock_user2.name = "Test User 2"
        mock_user2.email = "test2@example.com"
        mock_user2.machine_description = None
        mock_user2.created_at = datetime.now()

        mock_list_users.return_value = [mock_user1, mock_user2]

        # Run command
        result = self.runner.invoke(cli, ["list-machine-users"])

        assert result.exit_code == 0
        assert "Found 2 machine user(s):" in result.output
        assert "🤖 Test User 1" in result.output
        assert "🤖 Test User 2" in result.output
        mock_list_users.assert_called_once()

    @patch("src.cli.DatabaseManager")
    @patch("src.cli.list_machine_users")
    def test_list_machine_users_empty(self, mock_list_users, mock_db_manager):
        """Test list-machine-users CLI command with no users."""
        # Mock database operations
        mock_session = AsyncMock()
        mock_db_manager.return_value.async_session.return_value.__aenter__.return_value = mock_session
        mock_db_manager.return_value.close = AsyncMock()

        mock_list_users.return_value = []

        # Run command
        result = self.runner.invoke(cli, ["list-machine-users"])

        assert result.exit_code == 0
        assert "No machine users found." in result.output


class TestMachineUserQuota:
    """Test quota functionality for machine users."""

    @pytest.mark.asyncio
    async def test_machine_user_gets_higher_quota(self):
        """Test that machine users get higher quota than regular users."""
        from unittest.mock import AsyncMock

        from src.api.app import get_user_identity_and_daily_quota
        from src.api.schemas import UserModel

        # Create mock request
        mock_request = AsyncMock()

        # Create machine user
        machine_user = UserModel(
            id="machine_test123",
            name="Test Machine User",
            email="machine@example.com",
            user_type=UserType.MACHINE,
            threads=[],
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
        )

        # Create regular user
        regular_user = UserModel(
            id="regular_test123",
            name="Test Regular User",
            email="regular@example.com",
            user_type=UserType.REGULAR,
            threads=[],
            created_at="2023-01-01T00:00:00",
            updated_at="2023-01-01T00:00:00",
        )

        # Test quota assignment
        machine_result = await get_user_identity_and_daily_quota(
            mock_request, machine_user
        )
        regular_result = await get_user_identity_and_daily_quota(
            mock_request, regular_user
        )

        # Machine user should have much higher quota
        assert machine_result["prompt_quota"] == 1000  # Machine user quota
        assert regular_result["prompt_quota"] == 25  # Regular user quota
        assert machine_result["prompt_quota"] > regular_result["prompt_quota"]
