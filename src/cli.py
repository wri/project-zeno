#!/usr/bin/env python3
"""
Project Zeno Machine User CLI

A single-file CLI tool for managing machine users and API keys.
Machine users are special user accounts designed for programmatic access to the API.

Usage:
    python src/cli.py create-machine-user --name "Load Testing Bot" --email "load@test.com" --description "For load testing"
    python src/cli.py create-machine-user --name "API Bot" --email "api@test.com" --create-key --key-name "prod-key"
    python src/cli.py create-api-key --user-id "user_123" --key-name "test-key" --expires-days 90
    python src/cli.py list-machine-users
    python src/cli.py list-api-keys --user-id "user_123"
    python src/cli.py rotate-key --key-id "key_456"
    python src/cli.py revoke-key --key-id "key_456"
"""

import asyncio
import secrets
import uuid
from datetime import datetime
from typing import Optional

import bcrypt
import click
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.auth.machine_user import MACHINE_USER_PREFIX
from src.api.data_models import MachineUserKeyOrm, UserOrm, UserType
from src.utils.config import APISettings


class DatabaseManager:
    """Handles database connections and operations"""

    def __init__(self):
        self.engine = create_async_engine(APISettings.database_url)
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def get_session(self) -> AsyncSession:
        """Get database session"""
        async with self.async_session() as session:
            yield session

    async def close(self):
        """Close database connection"""
        await self.engine.dispose()


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key with prefix, secret, and hash.

    Returns:
        tuple: (full_token, prefix, hash_for_storage)
    """
    # Generate 8-character prefix and 32-character secret
    # Use token_hex to avoid underscores in prefix
    prefix = secrets.token_hex(4)[:8]  # 8 chars, no underscores
    secret = secrets.token_hex(16)  # 32 chars

    # Create full token: zeno-key_<prefix>_<secret>
    full_token = f"{MACHINE_USER_PREFIX}_{prefix}_{secret}"

    # Hash the secret for storage
    secret_hash = bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()

    return full_token, prefix, secret_hash


async def create_machine_user(
    session: AsyncSession,
    name: str,
    email: str,
    description: Optional[str] = None,
) -> UserOrm:
    """Create a new machine user"""

    # Check if email already exists
    existing_user = await session.execute(
        select(UserOrm).where(UserOrm.email == email)
    )
    if existing_user.scalar_one_or_none():
        raise ValueError(f"User with email {email} already exists")

    # Create machine user
    user_id = f"machine_{uuid.uuid4().hex[:12]}"
    user = UserOrm(
        id=user_id,
        name=name,
        email=email,
        user_type=UserType.MACHINE.value,
        is_machine_user=True,
        machine_description=description,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    session.add(user)
    await session.commit()
    await session.refresh(user)

    return user


async def create_api_key(
    session: AsyncSession,
    user_id: str,
    key_name: str,
    expires_at: Optional[datetime] = None,
) -> tuple[str, MachineUserKeyOrm]:
    """Create a new API key for a machine user"""

    # Verify user exists and is a machine user
    user = await session.execute(select(UserOrm).where(UserOrm.id == user_id))
    user = user.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")
    if not user.is_machine_user:
        raise ValueError(f"User {user_id} is not a machine user")

    # Generate API key
    full_token, prefix, secret_hash = generate_api_key()

    # Create key record
    api_key = MachineUserKeyOrm(
        user_id=user_id,
        key_name=key_name,
        key_hash=secret_hash,
        key_prefix=prefix,
        expires_at=expires_at,
        created_at=datetime.now(),
        is_active=True,
    )

    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    return full_token, api_key


async def list_machine_users(session: AsyncSession) -> list[UserOrm]:
    """List all machine users"""
    result = await session.execute(
        select(UserOrm).where(UserOrm.is_machine_user == True)  # noqa: E712
    )
    return result.scalars().all()


async def list_api_keys(
    session: AsyncSession, user_id: str
) -> list[MachineUserKeyOrm]:
    """List all API keys for a machine user"""
    result = await session.execute(
        select(MachineUserKeyOrm).where(MachineUserKeyOrm.user_id == user_id)
    )
    return result.scalars().all()


async def rotate_api_key(
    session: AsyncSession, key_id: str
) -> tuple[str, MachineUserKeyOrm]:
    """Rotate an API key (generate new secret, keep same prefix)"""

    # Get existing key
    result = await session.execute(
        select(MachineUserKeyOrm).where(MachineUserKeyOrm.id == key_id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise ValueError(f"API key {key_id} not found")

    # Generate new secret with same prefix
    secret = secrets.token_hex(16)
    full_token = f"{MACHINE_USER_PREFIX}_{key.key_prefix}_{secret}"
    secret_hash = bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()

    # Update key
    key.key_hash = secret_hash
    key.updated_at = datetime.now()

    await session.commit()
    await session.refresh(key)

    return full_token, key


async def revoke_api_key(
    session: AsyncSession, key_id: str
) -> MachineUserKeyOrm:
    """Revoke an API key"""

    # Get existing key
    result = await session.execute(
        select(MachineUserKeyOrm).where(MachineUserKeyOrm.id == key_id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise ValueError(f"API key {key_id} not found")

    # Deactivate key
    key.is_active = False
    key.updated_at = datetime.now()

    await session.commit()
    await session.refresh(key)

    return key


# CLI Commands
@click.group()
def cli():
    """Zeno Machine User Management CLI"""
    pass


@cli.command("create-machine-user")
@click.option("--name", required=True, help="Name of the machine user")
@click.option("--email", required=True, help="Email of the machine user")
@click.option("--description", help="Description of the machine user")
@click.option(
    "--create-key", is_flag=True, help="Also create an initial API key"
)
@click.option(
    "--key-name",
    default="default",
    help='Name for the initial API key (default: "default")',
)
def create_machine_user_command(
    name: str,
    email: str,
    description: Optional[str],
    create_key: bool,
    key_name: str,
):
    """Create a new machine user"""

    async def _create():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                user = await create_machine_user(
                    session, name, email, description
                )
                click.echo("✅ Created machine user:")
                click.echo(f"   ID: {user.id}")
                click.echo(f"   Name: {user.name}")
                click.echo(f"   Email: {user.email}")
                if user.machine_description:
                    click.echo(f"   Description: {user.machine_description}")
                click.echo(f"   Created: {user.created_at}")

                if create_key:
                    click.echo("\n🔑 Creating initial API key...")
                    full_token, api_key = await create_api_key(
                        session, user.id, key_name
                    )
                    click.echo("✅ Created API key:")
                    click.echo(f"   Key ID: {api_key.id}")
                    click.echo(f"   Name: {api_key.key_name}")
                    click.echo(f"   Token: {full_token}")
                    click.echo(f"   Prefix: {api_key.key_prefix}")
                    click.echo(f"   Created: {api_key.created_at}")
                    click.echo(
                        "\n⚠️  IMPORTANT: Save this token now - it won't be shown again!"
                    )
        finally:
            await db.close()

    asyncio.run(_create())


@cli.command("create-api-key")
@click.option("--user-id", required=True, help="ID of the machine user")
@click.option("--key-name", required=True, help="Name for the API key")
@click.option(
    "--expires-days", type=int, help="Number of days until key expires"
)
def create_api_key_command(
    user_id: str, key_name: str, expires_days: Optional[int]
):
    """Create a new API key for a machine user"""

    async def _create():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                expires_at = None
                if expires_days:
                    from datetime import timedelta

                    expires_at = datetime.now() + timedelta(days=expires_days)

                full_token, api_key = await create_api_key(
                    session, user_id, key_name, expires_at
                )

                click.echo("✅ Created API key:")
                click.echo(f"   Key ID: {api_key.id}")
                click.echo(f"   Name: {api_key.key_name}")
                click.echo(f"   Token: {full_token}")
                click.echo(f"   Prefix: {api_key.key_prefix}")
                if api_key.expires_at:
                    click.echo(f"   Expires: {api_key.expires_at}")
                click.echo(f"   Created: {api_key.created_at}")
                click.echo(
                    "\n⚠️  IMPORTANT: Save this token now - it won't be shown again!"
                )
        finally:
            await db.close()

    asyncio.run(_create())


@cli.command("list-machine-users")
def list_machine_users_command():
    """List all machine users"""

    async def _list():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                users = await list_machine_users(session)

                if not users:
                    click.echo("No machine users found.")
                    return

                click.echo(f"Found {len(users)} machine user(s):")
                click.echo("")

                for user in users:
                    click.echo(f"🤖 {user.name}")
                    click.echo(f"   ID: {user.id}")
                    click.echo(f"   Email: {user.email}")
                    if user.machine_description:
                        click.echo(
                            f"   Description: {user.machine_description}"
                        )
                    click.echo(f"   Created: {user.created_at}")
                    click.echo("")
        finally:
            await db.close()

    asyncio.run(_list())


@cli.command("list-api-keys")
@click.option("--user-id", required=True, help="ID of the machine user")
def list_api_keys_command(user_id: str):
    """List all API keys for a machine user"""

    async def _list():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                keys = await list_api_keys(session, user_id)

                if not keys:
                    click.echo(f"No API keys found for user {user_id}.")
                    return

                click.echo(f"Found {len(keys)} API key(s) for user {user_id}:")
                click.echo("")

                for key in keys:
                    status = "🟢 Active" if key.is_active else "🔴 Inactive"
                    click.echo(f"🔑 {key.key_name} - {status}")
                    click.echo(f"   Key ID: {key.id}")
                    click.echo(f"   Prefix: {key.key_prefix}")
                    if key.expires_at:
                        click.echo(f"   Expires: {key.expires_at}")
                    if key.last_used_at:
                        click.echo(f"   Last Used: {key.last_used_at}")
                    click.echo(f"   Created: {key.created_at}")
                    click.echo("")
        finally:
            await db.close()

    asyncio.run(_list())


@cli.command("rotate-key")
@click.option("--key-id", required=True, help="ID of the API key to rotate")
def rotate_key_command(key_id: str):
    """Rotate an API key (generate new secret)"""

    async def _rotate():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                full_token, api_key = await rotate_api_key(session, key_id)

                click.echo("✅ Rotated API key:")
                click.echo(f"   Key ID: {api_key.id}")
                click.echo(f"   Name: {api_key.key_name}")
                click.echo(f"   New Token: {full_token}")
                click.echo(f"   Prefix: {api_key.key_prefix}")
                click.echo(f"   Updated: {api_key.updated_at}")
                click.echo(
                    "\n⚠️  IMPORTANT: Save this new token now - it won't be shown again!"
                )
                click.echo("   The old token is now invalid.")
        finally:
            await db.close()

    asyncio.run(_rotate())


@cli.command("revoke-key")
@click.option("--key-id", required=True, help="ID of the API key to revoke")
@click.confirmation_option(
    prompt="Are you sure you want to revoke this API key?"
)
def revoke_key_command(key_id: str):
    """Revoke an API key"""

    async def _revoke():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                api_key = await revoke_api_key(session, key_id)

                click.echo("✅ Revoked API key:")
                click.echo(f"   Key ID: {api_key.id}")
                click.echo(f"   Name: {api_key.key_name}")
                click.echo(f"   Prefix: {api_key.key_prefix}")
                click.echo(f"   Revoked: {api_key.updated_at}")
                click.echo("\n🔴 This key is now inactive and cannot be used.")
        finally:
            await db.close()

    asyncio.run(_revoke())


if __name__ == "__main__":
    cli()
