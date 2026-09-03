#!/usr/bin/env python3
"""
Project Zeno Machine User CLI

A single-file CLI tool for managing machine users and API keys.
Machine users are special user accounts designed for programmatic access to the API.
API keys use the format: zeno-key:prefix:secret

Usage:
    python src/api/cli.py create-machine-user --name "Load Testing Bot" --email "load@test.com" --description "For load testing"
    python src/api/cli.py create-machine-user --name "API Bot" --email "api@test.com" --create-key --key-name "prod-key"
    python src/api/cli.py create-api-key --user-id "user_123" --key-name "test-key" --expires-days 90
    python src/api/cli.py list-machine-users
    python src/api/cli.py list-api-keys --user-id "user_123"
    python src/api/cli.py rotate-key --key-id "key_456"
    python src/api/cli.py revoke-key --key-id "key_456"
    python src/api/cli.py make-user-admin --email "admin@example.com"
    python src/api/cli.py build-aois --source custom --prune --dry-run
"""

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Optional

import bcrypt
import click
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.auth.machine_user import MACHINE_USER_PREFIX
from src.api.auth.scopes import KNOWN_SCOPES
from src.api.data_models import (
    MachineUserKeyOrm,
    UserOrm,
    UserType,
)
from src.api.services.aoi_sync import (
    prune_orphan_custom_aois,
    upsert_custom_aoi,
)
from src.shared.aoi_geometry import (
    bbox_float_array_sql,
    multipolygon_sql,
)
from src.shared.config import SharedSettings
from src.shared.geocoding_helpers import (
    AOI_SOURCE_ID_COLUMNS,
    GADM_LEVELS,
    GADM_STANDARD_ID_RE,
    SOURCE_STAGING_TABLES,
)


class DatabaseManager:
    """Handles database connections and operations"""

    def __init__(self):
        self.engine = create_async_engine(SharedSettings.database_url)
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


def _validate_scopes(scopes: tuple) -> list[str]:
    """Reject unknown scopes so a typo never silently mints a dead key."""
    unknown = sorted(set(scopes) - KNOWN_SCOPES)
    if unknown:
        raise click.BadParameter(
            f"Unknown scope(s): {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(KNOWN_SCOPES))}"
        )
    return list(scopes)


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key with prefix, secret, and hash.

    Returns:
        tuple: (full_token, prefix, hash_for_storage)
    """
    # Generate 8-character prefix and 32-character secret
    # Use token_hex to avoid colons in prefix
    prefix = secrets.token_hex(4)[:8]  # 8 chars, no colons
    secret = secrets.token_hex(16)  # 32 chars

    # Create full token: zeno-key:prefix:secret
    full_token = f"{MACHINE_USER_PREFIX}:{prefix}:{secret}"

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
    scopes: Optional[list[str]] = None,
) -> tuple[str, MachineUserKeyOrm]:
    """Create a new API key for a machine user"""

    # Verify user exists and is a machine user
    user = await session.execute(select(UserOrm).where(UserOrm.id == user_id))
    user = user.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found")
    if user.user_type != UserType.MACHINE.value:
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
        scopes=scopes or [],
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
        select(UserOrm).where(UserOrm.user_type == UserType.MACHINE.value)
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
    full_token = f"{MACHINE_USER_PREFIX}:{key.key_prefix}:{secret}"
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


async def make_user_admin(session: AsyncSession, email: str) -> UserOrm:
    """Make a user admin by setting their user_type to admin"""

    # Find user by email (case-insensitive)
    email_lower = email.lower()
    result = await session.execute(
        select(UserOrm).where(func.lower(UserOrm.email) == email_lower)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User with email {email} not found")

    # Update user type to admin
    user.user_type = UserType.ADMIN.value
    user.updated_at = datetime.now()

    await session.commit()
    await session.refresh(user)

    return user


async def make_user_pro(session: AsyncSession, email: str) -> UserOrm:
    """Make a user pro by setting their user_type to pro"""

    # Find user by email (case-insensitive)
    email_lower = email.lower()
    result = await session.execute(
        select(UserOrm).where(func.lower(UserOrm.email) == email_lower)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User with email {email} not found")

    # Update user type to pro
    user.user_type = UserType.PRO.value
    user.updated_at = datetime.now()

    await session.commit()
    await session.refresh(user)

    return user


async def make_user_superuser(session: AsyncSession, email: str) -> UserOrm:
    """Make a user superuser by setting their user_type to superuser"""

    email_lower = email.lower()
    result = await session.execute(
        select(UserOrm).where(func.lower(UserOrm.email) == email_lower)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User with email {email} not found")

    user.user_type = UserType.SUPERUSER.value
    user.updated_at = datetime.now()

    await session.commit()
    await session.refresh(user)

    return user


# CLI Commands
@click.group()
def cli():
    """Zeno User Management CLI"""
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
@click.option(
    "--scope",
    "scopes",
    multiple=True,
    help="Authorization scope for the initial key; repeatable.",
)
def create_machine_user_command(
    name: str,
    email: str,
    description: Optional[str],
    create_key: bool,
    key_name: str,
    scopes: tuple,
):
    """Create a new machine user"""

    scope_list = _validate_scopes(scopes)

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
                        session, user.id, key_name, scopes=scope_list
                    )
                    click.echo("✅ Created API key:")
                    click.echo(f"   Key ID: {api_key.id}")
                    click.echo(f"   Name: {api_key.key_name}")
                    click.echo(f"   Token: {full_token}")
                    click.echo(f"   Prefix: {api_key.key_prefix}")
                    click.echo(
                        f"   Scopes: {', '.join(api_key.scopes) or '(none)'}"
                    )
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
@click.option(
    "--scope",
    "scopes",
    multiple=True,
    help="Authorization scope for the key; repeatable.",
)
def create_api_key_command(
    user_id: str, key_name: str, expires_days: Optional[int], scopes: tuple
):
    """Create a new API key for a machine user"""

    scope_list = _validate_scopes(scopes)

    async def _create():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                expires_at = None
                if expires_days:
                    from datetime import timedelta

                    expires_at = datetime.now() + timedelta(days=expires_days)

                full_token, api_key = await create_api_key(
                    session, user_id, key_name, expires_at, scopes=scope_list
                )

                click.echo("✅ Created API key:")
                click.echo(f"   Key ID: {api_key.id}")
                click.echo(f"   Name: {api_key.key_name}")
                click.echo(f"   Token: {full_token}")
                click.echo(f"   Prefix: {api_key.key_prefix}")
                click.echo(
                    f"   Scopes: {', '.join(api_key.scopes) or '(none)'}"
                )
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
                    click.echo(
                        f"   Scopes: {', '.join(key.scopes) or '(none)'}"
                    )
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


@cli.command("make-user-admin")
@click.option("--email", required=True, help="Email of the user to make admin")
def make_user_admin_command(email: str):
    """Make a user admin by setting their user_type to admin"""

    async def _make_admin():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                user = await make_user_admin(session, email)

                click.echo("✅ Made user admin:")
                click.echo(f"   ID: {user.id}")
                click.echo(f"   Name: {user.name}")
                click.echo(f"   Email: {user.email}")
                click.echo(f"   User Type: {user.user_type}")
                click.echo(f"   Updated: {user.updated_at}")
        except ValueError as e:
            click.echo(f"❌ Error: {e}", err=True)
        finally:
            await db.close()

    asyncio.run(_make_admin())


@cli.command("make-user-pro")
@click.option("--email", required=True, help="Email of the user to make pro")
def make_user_pro_command(email: str):
    """Make a user pro by setting their user_type to pro"""

    async def _make_pro():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                user = await make_user_pro(session, email)

                click.echo("✅ Made user pro:")
                click.echo(f"   ID: {user.id}")
                click.echo(f"   Name: {user.name}")
                click.echo(f"   Email: {user.email}")
                click.echo(f"   User Type: {user.user_type}")
                click.echo(f"   Updated: {user.updated_at}")
        except ValueError as e:
            click.echo(f"❌ Error: {e}", err=True)
        finally:
            await db.close()

    asyncio.run(_make_pro())


@cli.command("make-user-superuser")
@click.option(
    "--email", required=True, help="Email of the user to make superuser"
)
def make_user_superuser_command(email: str):
    """Make a user superuser by setting their user_type to superuser"""

    async def _make_superuser():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                user = await make_user_superuser(session, email)

                click.echo("✅ Made user superuser:")
                click.echo(f"   ID: {user.id}")
                click.echo(f"   Name: {user.name}")
                click.echo(f"   Email: {user.email}")
                click.echo(f"   User Type: {user.user_type}")
                click.echo(f"   Updated: {user.updated_at}")
        except ValueError as e:
            click.echo(f"❌ Error: {e}", err=True)
        finally:
            await db.close()

    asyncio.run(_make_superuser())


@cli.command("list-pro-users")
def list_pro_users_command():
    """List all pro users"""

    async def _list_pro_users():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                result = await session.execute(
                    select(UserOrm).where(
                        UserOrm.user_type == UserType.PRO.value
                    )
                )
                pro_users = result.scalars().all()

                if not pro_users:
                    click.echo("No pro users found")
                else:
                    click.echo(f"\nFound {len(pro_users)} pro user(s):\n")
                    for user in pro_users:
                        click.echo(
                            f"  • {user.name} ({user.email}) - ID: {user.id}"
                        )
        finally:
            await db.close()

    asyncio.run(_list_pro_users())


def _parse_cli_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@cli.command("ingest-langfuse-traces")
@click.option(
    "--since",
    help="ISO start (overrides watermark). Required with --backfill.",
)
@click.option("--until", help="ISO end (default: now).")
@click.option(
    "--backfill", is_flag=True, help="Historical backfill from --since."
)
@click.option(
    "--environment",
    "environments",
    multiple=True,
    help="Filter to environment(s); repeatable. Default: all.",
)
@click.option(
    "--overlap-hours",
    type=int,
    default=12,
    help="Re-scan overlap before watermark.",
)
@click.option(
    "--chunk-hours",
    type=int,
    default=24,
    help="Window chunk size for backfill.",
)
@click.option(
    "--batch-size",
    type=int,
    default=300,
    help="Fetch page / upsert batch size.",
)
@click.option(
    "--dry-run", is_flag=True, help="Fetch + parse but do not write."
)
def ingest_langfuse_traces_command(
    since: Optional[str],
    until: Optional[str],
    backfill: bool,
    environments: tuple,
    overlap_hours: int,
    chunk_hours: int,
    batch_size: int,
    dry_run: bool,
):
    """Ingest Langfuse traces into Postgres (idempotent upsert)."""
    from src.api.services.langfuse.ingest import (
        resolve_start_watermark,
        run_ingestion,
    )

    async def _run():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                until_dt = (
                    _parse_cli_dt(until)
                    if until
                    else datetime.now(timezone.utc)
                )
                envs = list(environments) or [None]
                for env in envs:
                    if since:
                        since_dt = _parse_cli_dt(since)
                    elif backfill:
                        raise click.UsageError("--backfill requires --since")
                    else:
                        wm = await resolve_start_watermark(session, env)
                        if wm is None:
                            since_dt = until_dt - timedelta(hours=24)
                            click.echo(
                                "ℹ️  No watermark; defaulting to last 24h "
                                "(use --backfill --since for history)."
                            )
                        else:
                            since_dt = wm - timedelta(hours=overlap_hours)

                    result = await run_ingestion(
                        session,
                        since=since_dt,
                        until=until_dt,
                        environment=env,
                        chunk_hours=chunk_hours,
                        batch_size=batch_size,
                        dry_run=dry_run,
                    )
                    click.echo(
                        f"[{env or 'all'}] {since_dt.isoformat()} → {until_dt.isoformat()} | "
                        f"fetched={result.fetched} upserted={result.upserted} "
                        f"chunks={result.chunks_total} failed={result.chunks_failed} "
                        f"status={result.status} watermark={result.watermark}"
                    )
        finally:
            await db.close()

    asyncio.run(_run())


@cli.command("backfill-turn-fields")
@click.option(
    "--batch-size",
    type=int,
    default=500,
    help="Sessions renumbered per committed batch.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Report how many rows would change without writing.",
)
def backfill_turn_fields_command(batch_size: int, dry_run: bool):
    """Backfill turn_index / is_final / per-turn diffs for pre-existing rows.

    Run once after deploying the turn-analytics migrations (which add these columns
    empty, keeping the data pass out of the blocking deploy path). New rows are set
    during normal ingest. Idempotent — safe to re-run (writes nothing the 2nd time).
    """
    from src.api.services.langfuse.ingest import backfill_turn_fields

    async def _run():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                written = await backfill_turn_fields(
                    session, batch_size=batch_size, dry_run=dry_run
                )
                verb = "would update" if dry_run else "updated"
                click.echo(f"backfill-turn-fields: {verb} {written} row(s)")
        finally:
            await db.close()

    asyncio.run(_run())


@cli.command("langfuse-model-prices")
@click.option("--hours", type=int, default=24, help="Look-back window.")
@click.option("--environment", default=None, help="Filter to one environment.")
def langfuse_model_prices_command(hours: int, environment: Optional[str]):
    """Report which models Langfuse is failing to price.

    Langfuse computes cost by matching an observation's model name against its
    model-definition table. A model it does not recognise — a preview name, or a
    newly configured one — is recorded with usage but **zero cost**, so
    cost-per-query silently understates by that model's whole share, with
    nothing in the data to say so.

    For every model flagged UNPRICED here, add a model definition with its
    prices in Langfuse (Settings → Models), then re-run
    ``ingest-langfuse-traces --backfill --since`` over the affected window to
    recompute the stored costs.
    """
    from src.api.services.langfuse.fetch import LangfuseClient

    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=hours)
    client = LangfuseClient.from_env()
    # Every type, then filter on "has a model and reported usage": embeddings
    # are billable too, and an unpriced embedding model is just as invisible as
    # an unpriced chat one.
    observations = client.fetch_observations_window(
        since, until, environment, obs_type=None
    )

    # model -> [calls, tokens, cost, priced_calls]
    stats: dict = {}
    for o in observations:
        model = o.get("model")
        usage = o.get("usageDetails") or {}
        if not model or not usage:
            continue
        cost = o.get("totalCost") or 0
        row = stats.setdefault(model, [0, 0, 0.0, 0])
        row[0] += 1
        row[1] += int(usage.get("total") or 0)
        row[2] += float(cost)
        if cost:
            row[3] += 1

    if not stats:
        click.echo(f"No billable LLM calls in the last {hours}h.")
        return

    click.echo(
        f"{'model':38} {'calls':>7} {'tokens':>10} {'cost':>11}  status"
    )
    unpriced = []
    for model, (calls, tokens, cost, priced) in sorted(
        stats.items(), key=lambda kv: -kv[1][1]
    ):
        if priced == 0:
            status = "UNPRICED"
            unpriced.append(model)
        elif priced < calls:
            status = f"PARTIAL ({priced}/{calls} priced)"
        else:
            status = "ok"
        click.echo(
            f"{model[:38]:38} {calls:>7} {tokens:>10,} {cost:>11.6f}  {status}"
        )

    if unpriced:
        click.echo(
            "\n⚠️  Unpriced models contribute tokens but no cost: "
            + ", ".join(unpriced)
        )
        click.echo(
            "   Add a model definition for each in Langfuse, then re-ingest "
            "the window."
        )
    else:
        click.echo("\n✅ Every model in this window is priced.")


# ---------------------------------------------------------------------------
# build-aois: populate the unified `aois` / `user_aois` tables
# ---------------------------------------------------------------------------

# Reference sources first, custom last (custom depends only on custom_areas).
_BUILD_SOURCES = ["gadm", "kba", "wdpa", "landmark", "custom"]

# This transform leaves `aois.properties` (JSONB) NULL. The column holds two
# kinds of value that no code writes yet: the attributes of an uploaded custom
# AOI, and the source columns that do not map to a typed column. Both are
# follow-up work.

# Which source column carries the ISO3 country code(s), per reference source.
# Resolved case-insensitively at runtime: geometries_* are built by GeoPandas
# `to_postgis` and preserve the source file's (often upper-case) column casing.
_ISO3_SOURCE_COLUMNS = {
    "gadm": ["GID_0"],
    "kba": ["ISO3"],
    "wdpa": ["iso3"],
    "landmark": ["iso_code"],
}

# GADM 4.1 ships the literal string "NA" as its no-data marker, and ingest
# composes display names from the NAME_* columns without recognising it, so
# England's row is named "NA, United Kingdom" and is unfindable by search.
# 2,930 rows are affected globally. See SPEC-PR7 / PZB-1271.
_GADM_NO_DATA_NAME = "NA"

# Rule A adopts a candidate name only when it holds this share of the parent's
# *named* immediate children. GADM's own child rows disagree with each other,
# so unanimity is not available: England's level-2 children include two that
# say "NA", Cork's include one "Cork City", Zuid-Holland's one "Zuid Hollandse
# Meren". A strict majority keeps all three, and refuses the all-NA ghost row
# whose two children split 1-1 between England and Scotland. The one
# plurality-adjacent case it admits is CHL.15.1_1 -> Tamarugal (5 of 7, GADM's
# row spanning two Chilean provinces); raise this to 0.8 to exclude it.
_GADM_CHILD_NAME_MIN_SHARE = 0.5

# Rule B's level. GADM shifted names down a level only for district-counties
# holding a single municipality (Bristol, Tameside, Trafford, Wiltshire ...);
# applying it further down would rename a unit after an unrelated child.
_GADM_SHIFTED_NAME_SUBTYPE = "district-county"


async def _table_exists(session: AsyncSession, table: str) -> bool:
    result = await session.execute(
        text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
    )
    return bool(result.scalar())


async def _resolve_column(
    session: AsyncSession, table: str, candidates: list[str]
) -> Optional[str]:
    """Return the real (correctly-cased) name of the first present candidate."""
    for cand in candidates:
        result = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND lower(column_name) = lower(:c) "
                "LIMIT 1"
            ),
            {"table": table, "c": cand},
        )
        found = result.scalar()
        if found:
            return found
    return None


class _GadmLevel(NamedTuple):
    """One GADM admin level's subtype and its two columns in staging."""

    subtype: str
    id_col: str
    name_col: str


def _gadm_repair_levels() -> list[_GadmLevel]:
    """GADM's admin levels, shallowest first, from ``GADM_LEVELS``.

    One definition of the hierarchy, so the repair rules can pair a level with
    the one below it (``zip(levels, levels[1:])``). A parent and its children
    share the parent's ``id_col``, and both carry the parent's name in their own
    ``name_col``, which is what lets a broken parent look one level down.
    """
    return [
        _GadmLevel(subtype, level["col_name"], level["name_col"])
        for subtype, level in GADM_LEVELS.items()
    ]


async def _derive_gadm_name_repairs(
    session: AsyncSession, table: str, id_col: str
) -> dict[str, str]:
    """Derive ``{source_id: repaired display name}`` from GADM's hierarchy.

    Read-only: staging is never written, so the map is recomputed identically on
    every build and re-applies itself after any re-ingest, GADM v5 included.

    Two rules, both taking the name from rows GADM did fill in:

    * **A, parent name from children.** A row whose own ``NAME_n`` is ``'NA'``
      adopts the name its immediate children carry in *their* ``NAME_n``, when
      one candidate holds a strict majority of the named children. Repairs
      England, Cork and Zuid-Holland at level 1, and at level 2 the multi-child
      counties whose name GADM only stored one level down (Warwickshire,
      Derbyshire, Greater London ...).
    * **B, leaf name from an only child.** A district-county row holding
      exactly one municipality child, which must itself be named, adopts that
      child's name. A district with one named child *and* one ``'NA'`` child is
      refused: the SQL counts every child, not just the named ones, so the pair
      has to be unambiguous. Repairs Bristol and 57 others, where GADM shifted
      the name down a level rather than omitting it. Rule A wins where both
      could fire.

    Only the broken leading segment of the display name is replaced; every
    parent segment is left byte-identical, so no row's name changes except at
    the position GADM left as ``'NA'``. Rows the rules cannot reach (no
    children, a tie, a multi-child parent with no majority, an unnamed only
    child) keep the name they have today.

    Known gap, accepted: only the *leading* segment is repaired, so a Rule B
    family leaves the child itself reading "Bristol, NA, England, United
    Kingdom" -- the parent's own name is fixed, the same name sitting in the
    child's middle segment is not. Recomposing a display name from its repaired
    ancestors is SPEC-PR8's design and the durable fix; patching middle
    segments by string surgery here is not.
    """
    # One catalogue read for every level: `_resolve_column` costs a round trip
    # per candidate and returns the real casing, which nothing here needs --
    # the column names come from GADM_LEVELS and are quoted as declared.
    result = await session.execute(
        text(
            "SELECT lower(column_name) FROM information_schema.columns "
            "WHERE table_name = :t"
        ),
        {"t": table},
    )
    present = {row[0] for row in result.all()}

    levels: list[_GadmLevel] = []
    for level in _gadm_repair_levels():
        missing = [
            col
            for col in (level.id_col, level.name_col)
            if col.lower() not in present
        ]
        if missing:
            # A level GADM_LEVELS declares but staging does not carry means a
            # partial ingest: say so rather than quietly repairing less.
            click.echo(
                f"⚠️  gadm: level '{level.subtype}' skipped by the name "
                f"repair ({', '.join(missing)} not in {table})."
            )
        else:
            levels.append(level)

    # Each rule pairs a level with the one directly below it.
    pairs = list(zip(levels, levels[1:]))
    if not pairs:
        return {}

    params: dict[str, object] = {
        "na": _GADM_NO_DATA_NAME,
        "na_prefix": f"{_GADM_NO_DATA_NAME}, %",
        "min_share": _GADM_CHILD_NAME_MIN_SHARE,
    }
    votes: list[str] = []
    for i, (parent, child) in enumerate(pairs):
        params[f"parent_{i}"] = parent.subtype
        params[f"child_{i}"] = child.subtype
        # Identifiers cannot be bound, and these come from GADM_LEVELS, not
        # from data. Every value is a bound parameter. A NULL candidate fails
        # `NOT IN` on its own, so no null test is needed.
        votes.append(
            f"""
            SELECT CAST(p."{id_col}" AS TEXT) AS source_id,
                   c."{parent.name_col}" AS candidate,
                   count(*) AS votes
            FROM {table} p
            JOIN {table} c
              ON c.subtype = :child_{i}
             AND c."{parent.id_col}" = p."{parent.id_col}"
            WHERE p.subtype = :parent_{i}
              AND p."{parent.name_col}" = :na
              AND c."{parent.name_col}" NOT IN ('', :na)
            GROUP BY 1, 2
            """
        )

    ctes = [
        f"votes AS ({' UNION ALL '.join(votes)})",
        """ranked AS (
            SELECT source_id, candidate, votes,
                   sum(votes) OVER (PARTITION BY source_id) AS total
            FROM votes
        )""",
        """rule_a AS (
            -- No tie-break, and none possible: a strict majority of the votes
            -- admits at most one candidate per source_id. Drop :min_share to
            -- 0.5 or below and this CTE can emit several rows for one id,
            -- which `repairs` would carry through as duplicate repairs.
            SELECT source_id, candidate AS leaf
            FROM ranked
            WHERE votes > :min_share * total
        )""",
    ]
    repair_arms = ["SELECT source_id, leaf FROM rule_a"]

    # Rule B is level 2 only: the shifted-name pattern is a district-county
    # holding a single municipality. Emitted only when that level survived the
    # column check, so there is no empty sentinel CTE to reason about.
    b_pair = next(
        (
            (parent, child)
            for parent, child in pairs
            if parent.subtype == _GADM_SHIFTED_NAME_SUBTYPE
        ),
        None,
    )
    if b_pair is not None:
        parent, child = b_pair
        params["b_parent"] = parent.subtype
        params["b_child"] = child.subtype
        # The inner select groups, the outer only filters, so `min()` is
        # written once. It is the only child's name, because HAVING has already
        # restricted the group to one row; a NULL leaf fails `NOT IN`.
        ctes.append(
            f"""rule_b AS (
            SELECT source_id, leaf
            FROM (
                SELECT CAST(p."{id_col}" AS TEXT) AS source_id,
                       min(c."{child.name_col}") AS leaf
                FROM {table} p
                JOIN {table} c
                  ON c.subtype = :b_child
                 AND c."{parent.id_col}" = p."{parent.id_col}"
                WHERE p.subtype = :b_parent
                  AND p."{parent.name_col}" = :na
                GROUP BY 1
                HAVING count(*) = 1
            ) only_child
            WHERE leaf NOT IN ('', :na)
        )"""
        )
        # Rule A wins where both fire.
        repair_arms.append(
            "SELECT source_id, leaf FROM rule_b"
            " WHERE source_id NOT IN (SELECT source_id FROM rule_a)"
        )

    ctes.append(f"repairs AS ({' UNION ALL '.join(repair_arms)})")

    # substring past the marker drops the leading 'NA' and keeps the ', parent'
    # tail. DISTINCT ON collapses the duplicate ids the staging tables carry
    # (no unique constraint); duplicates of one id share their composed name.
    sql = f"""
        WITH {", ".join(ctes)}
        SELECT DISTINCT ON (r.source_id)
               r.source_id,
               r.leaf || substring(g.name FROM char_length(:na) + 1)
                 AS repaired
        FROM repairs r
        JOIN {table} g ON CAST(g."{id_col}" AS TEXT) = r.source_id
        WHERE g.name = :na OR g.name LIKE :na_prefix
        ORDER BY r.source_id, repaired
    """
    result = await session.execute(text(sql), params)
    return {row[0]: row[1] for row in result.all()}


async def _build_reference_aois(
    session: AsyncSession, source: str, *, nchunks: int, dry_run: bool
) -> int:
    """Transform one ``geometries_<source>`` table into ``aois`` (idempotent).

    The INSERT runs in ``nchunks`` passes partitioned by a hash of the source
    id -- each pass its own statement and its own transaction. This bounds the
    open transaction and makes a late failure resumable (committed chunks are
    kept). Every row for a given id hashes to the same chunk, so the per-chunk
    ``DISTINCT ON`` dedup and ``ON CONFLICT`` upsert stay correct with no
    cross-chunk boundary effects. Note chunking does *not* bound the cost of any
    single geometry -- that is the job of the part-wise repair in
    ``multipolygon_sql`` and the ``MATERIALIZED`` CTE (compute each shape once).

    The gadm name repair is derived once, before the loop, and passed in as one
    bound jsonb object. It has to be: it reads a row's *children*, which the
    hash partition scatters across other chunks, so a lookup inside the chunked
    statement would have to be careful never to be chunk-filtered. Deriving it
    once also pays for its self-join once (~20s on the full table) instead of
    once per pass.
    """
    table = SOURCE_STAGING_TABLES[source]
    id_col = AOI_SOURCE_ID_COLUMNS[source]

    iso3_col = await _resolve_column(
        session, table, _ISO3_SOURCE_COLUMNS[source]
    )
    iso3_expr = (
        f"string_to_array(NULLIF(btrim(\"{iso3_col}\"::text), ''), ';')"
        if iso3_col
        else "NULL::text[]"
    )

    # Only gadm carries broken source names, so every other source selects
    # `name` unchanged, joins nothing extra and binds no repair parameters.
    name_expr = "name"
    repair_join = ""
    repair_params: dict[str, object] = {}
    if source == "gadm":
        # subtype -> GADM admin level (0..5), in GADM_LEVELS declaration order.
        admin_expr = (
            "CASE subtype "
            + " ".join(
                f"WHEN '{st}' THEN {lvl}" for lvl, st in enumerate(GADM_LEVELS)
            )
            + " ELSE NULL END"
        )
        # Disputed territories (e.g. "Z01") lack a 3-letter ISO prefix; keep
        # the rows but flag them so search can exclude via its partial index.
        disputed_expr = f"NOT (\"{id_col}\" ~ '{GADM_STANDARD_ID_RE}')"

        repairs = await _derive_gadm_name_repairs(session, table, id_col)
        if repairs:
            click.echo(
                f"🔧 {source}: {len(repairs)} name(s) repaired from GADM's "
                "own hierarchy."
            )
            # One bound jsonb object rather than two arrays that have to stay
            # index-aligned: one hash join per pass, scaling with however many
            # rows the rules reach. Not chunk-filtered, on purpose -- see the
            # docstring.
            repair_join = (
                " LEFT JOIN jsonb_each_text(CAST(:repairs AS jsonb))"
                " AS r(repair_id, repair_name)"
                f' ON r.repair_id = CAST("{id_col}" AS TEXT)'
            )
            name_expr = "COALESCE(r.repair_name, name)"
            repair_params = {"repairs": json.dumps(repairs)}
        else:
            # Staging always carries GADM's 'NA' rows, so an empty map means
            # the rules reached nothing: never let that pass unremarked.
            click.echo(
                f"⚠️  {source}: no name(s) repaired from GADM's own hierarchy."
            )
    else:
        admin_expr = "NULL::smallint"
        disputed_expr = "false"

    # Normalize source geometry to a valid MultiPolygon once, then derive
    # geometry / bbox / area_km2 from the same shape.
    norm_geom = multipolygon_sql("geometry")
    # The geometries_* tables are bulk-loaded by GeoPandas with no unique
    # constraint, so the same id can appear on several rows (GADM does).
    # Postgres aborts the whole INSERT ... ON CONFLICT DO UPDATE if one
    # statement proposes the same conflict key twice, so collapse duplicates
    # here, keeping the largest geometry -- the real feature when the rest
    # are slivers. Ranking uses planar ST_Area on the *raw* column: it is
    # only a comparison, and this avoids recomputing the normalized shape.
    # ::bigint before abs(): hashtext returns int4 and abs(-2147483648)
    # overflows int4; widening first makes the modulo safe for every id.
    # AS MATERIALIZED: geom is read ~13 times downstream (the geometry itself,
    # ST_Area, ST_IsEmpty, and ~10 times inside the antimeridian bbox). A
    # single-use CTE would be inlined and the geometry repair re-evaluated at
    # each site; materializing computes each shape exactly once and stores it.
    sql = f"""
        WITH normalized AS MATERIALIZED (
            SELECT DISTINCT ON (CAST("{id_col}" AS TEXT))
                CAST("{id_col}" AS TEXT) AS source_id,
                {name_expr} AS name,
                subtype,
                {norm_geom} AS geom,
                {iso3_expr} AS iso3,
                {admin_expr} AS admin_level,
                {disputed_expr} AS is_disputed
            FROM {table}{repair_join}
            WHERE name IS NOT NULL AND geometry IS NOT NULL
              AND (abs(hashtext(CAST("{id_col}" AS TEXT))::bigint) % :nchunks)
                  = :chunk
            ORDER BY
                CAST("{id_col}" AS TEXT),
                ST_Area(geometry) DESC NULLS LAST,
                name
        )
        INSERT INTO aois (
            source, source_id, name, subtype, geometry,
            bbox, area_km2, iso3, admin_level, is_disputed
        )
        SELECT
            '{source}',
            source_id,
            name,
            subtype,
            geom,
            {bbox_float_array_sql("geom")},
            ST_Area(geom::geography) / 1e6,
            iso3,
            admin_level,
            is_disputed
        FROM normalized
        WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)
        ON CONFLICT (source, source_id) WHERE NOT is_deprecated
        DO UPDATE SET
            name = EXCLUDED.name,
            subtype = EXCLUDED.subtype,
            geometry = EXCLUDED.geometry,
            bbox = EXCLUDED.bbox,
            area_km2 = EXCLUDED.area_km2,
            iso3 = EXCLUDED.iso3,
            admin_level = EXCLUDED.admin_level,
            is_disputed = EXCLUDED.is_disputed,
            updated_at = now()
    """
    inserted = 0
    for chunk in range(nchunks):
        result = await session.execute(
            text(sql), {"nchunks": nchunks, "chunk": chunk, **repair_params}
        )
        inserted += result.rowcount
        # One transaction per chunk: bounds the open transaction and makes a
        # real run resumable. dry_run discards each chunk once its counts land.
        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    # Cheap accounting (no geometry work): one scan yields both figures.
    total_rows, distinct_ids = (
        await session.execute(
            text(
                f'SELECT count(*), count(DISTINCT CAST("{id_col}" AS TEXT)) '
                f"FROM {table} "
                f"WHERE name IS NOT NULL AND geometry IS NOT NULL"
            )
        )
    ).one()

    # Duplicate ids collapsed by DISTINCT ON, so the collapse is never silent.
    duplicates = total_rows - distinct_ids
    if duplicates:
        click.echo(
            f"⚠️  {source}: {duplicates} duplicate row(s) collapsed "
            f"(same {id_col}; kept the largest geometry)."
        )

    # Distinct ids whose largest representative row didn't coerce to a
    # non-empty MultiPolygon (so it never made it into aois). Derived by
    # arithmetic to avoid a second full-table ST_MakeValid pass.
    skipped = distinct_ids - inserted
    if skipped:
        click.echo(
            f"⚠️  {source}: {skipped} AOI(s) dropped (representative "
            f"geometry not coercible to a non-empty MultiPolygon)."
        )
    return inserted


async def _inspect_reference_aois(session: AsyncSession, source: str) -> None:
    """Print memory-light geometry stats for one ``geometries_<source>`` table.

    A diagnostic to size up before building: ``ST_NPoints`` /
    ``ST_NumGeometries`` walk the serialized structure without touching
    coordinates, and ``ST_GeometryType`` is cheap, so this is safe to run on
    tables that a full transform cannot survive.

    The part figures matter more than the per-row totals: the transform repairs
    each part separately, so its peak cost tracks the largest single part, while
    a high part count is what makes a whole-geometry repair blow up. The
    largest-part pass needs ``ST_Dump``, so it is slower than the rest.
    """
    table = SOURCE_STAGING_TABLES[source]
    id_col = AOI_SOURCE_ID_COLUMNS[source]

    (
        rows,
        distinct_ids,
        null_geom,
        max_pts,
        avg_pts,
        gt100k,
        gt500k,
        gt1m,
        max_parts,
        avg_parts,
    ) = (
        await session.execute(
            text(
                f'SELECT count(*), count(DISTINCT CAST("{id_col}" AS TEXT)), '
                "count(*) FILTER (WHERE geometry IS NULL), "
                "max(ST_NPoints(geometry)), "
                "round(avg(ST_NPoints(geometry))), "
                "count(*) FILTER (WHERE ST_NPoints(geometry) > 100000), "
                "count(*) FILTER (WHERE ST_NPoints(geometry) > 500000), "
                "count(*) FILTER (WHERE ST_NPoints(geometry) > 1000000), "
                "max(ST_NumGeometries(geometry)), "
                "round(avg(ST_NumGeometries(geometry))) "
                f"FROM {table}"
            )
        )
    ).one()

    click.echo(f"\n🔬 {source} ({table}):")
    click.echo(f"   rows: {rows}  distinct ids: {distinct_ids}")
    if null_geom:
        click.echo(f"   null geometry: {null_geom}")
    click.echo(
        f"   vertices/row -> max: {max_pts}  avg: "
        f"{int(avg_pts) if avg_pts is not None else 0}"
    )
    click.echo(
        f"   over threshold -> >100k: {gt100k}  >500k: {gt500k}  >1M: {gt1m}"
    )
    click.echo(
        f"   parts/row -> max: {max_parts}  avg: "
        f"{int(avg_parts) if avg_parts is not None else 0}"
    )

    max_part_pts = await session.scalar(
        text(
            f"SELECT max(ST_NPoints(d.geom)) FROM {table} w "
            "CROSS JOIN LATERAL ST_Dump(w.geometry) d"
        )
    )
    click.echo(f"   vertices in largest single part: {max_part_pts}")

    types = await session.execute(
        text(
            f"SELECT ST_GeometryType(geometry), count(*) FROM {table} "
            "WHERE geometry IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
        )
    )
    click.echo("   geometry types:")
    for gtype, cnt in types.all():
        click.echo(f"     {gtype}: {cnt}")


@cli.command("build-aois")
@click.option(
    "--source",
    "sources",
    multiple=True,
    type=click.Choice(_BUILD_SOURCES),
    help="Limit to source(s); repeatable. Default: all.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Run the transform in a transaction, report counts, then roll back.",
)
@click.option(
    "--chunks",
    default=16,
    type=click.IntRange(min=1),
    show_default=True,
    help=(
        "Hash-partitioned passes per reference source; each is its own "
        "statement and transaction. Higher = lower peak memory, more scans."
    ),
)
@click.option(
    "--inspect",
    is_flag=True,
    help=(
        "Don't build: print memory-light geometry stats (vertex distribution, "
        "types) per reference source, to size up before a real run."
    ),
)
@click.option(
    "--prune",
    is_flag=True,
    help=(
        "custom only: also delete the mirrored aois rows that have no "
        "custom_areas row. Off by default, because a wrong or empty "
        "custom_areas table makes every mirrored row look like an orphan. "
        "Combine with --dry-run to see the count first."
    ),
)
def build_aois_command(
    sources: tuple, dry_run: bool, chunks: int, inspect: bool, prune: bool
):
    """Populate the unified aois/user_aois tables from already-loaded data.

    Idempotent, set-based, in-DB transform of the reference geometries_*
    tables and custom_areas into the unified schema. Run post-deploy (heavy
    work must not run in the blocking migrate Job).

    The API reads aois, so this command is a precondition, not an extra. The
    reference sources do not change, so one build serves them. custom_areas
    does change, so re-run --source custom after a deploy that adds the
    write-through mirror. Add --prune on that run to remove the rows left by a
    delete that the mirror missed.
    """
    selected = list(sources) or _BUILD_SOURCES
    outcome = "would be upserted" if dry_run else "upserted"

    if prune and inspect:
        raise click.UsageError("--prune cannot run with --inspect.")
    if prune and "custom" not in selected:
        raise click.UsageError("--prune needs the custom source.")
    pruned = "would be removed" if dry_run else "removed"

    async def _inspect():
        db = DatabaseManager()
        try:
            async with db.async_session() as session:
                for source in selected:
                    if source == "custom":
                        click.echo(
                            "\n🔬 custom: skipped "
                            "(GeoJSON-string list, not a geometry column)."
                        )
                        continue
                    table = SOURCE_STAGING_TABLES[source]
                    if not await _table_exists(session, table):
                        click.echo(
                            f"⏭️  {source}: {table} not found, skipping."
                        )
                        continue
                    await _inspect_reference_aois(session, source)
        finally:
            await db.close()

    async def _run():
        db = DatabaseManager()
        committed: list[str] = []
        try:
            for source in selected:
                # Each build is independently idempotent and commits as it
                # goes (reference sources per chunk, custom once), so a late
                # failure never discards sources -- or chunks -- that already
                # succeeded; re-run resumes. The big reference tables are far
                # too large to hold in one open transaction.
                async with db.async_session() as session:
                    table = SOURCE_STAGING_TABLES[source]
                    if not await _table_exists(session, table):
                        click.echo(
                            f"⏭️  {source}: {table} not found, skipping."
                        )
                        continue

                    if source == "custom":
                        # The CRUD write-through uses this same SQL. This call
                        # has no area filter.
                        links = await upsert_custom_aoi(session)
                        click.echo(
                            f"✅ custom: {links} owner link(s) {outcome}."
                        )
                        if prune:
                            # The same session as the upsert, so --dry-run
                            # rolls the delete back with it.
                            gone = await prune_orphan_custom_aois(session)
                            click.echo(
                                f"🧹 custom: {gone} orphan row(s) {pruned}."
                            )
                    else:
                        n = await _build_reference_aois(
                            session, source, nchunks=chunks, dry_run=dry_run
                        )
                        click.echo(f"✅ {source}: {n} aoi row(s) {outcome}.")

                    # Reference sources self-commit per chunk; this trailing
                    # commit/rollback is then a no-op for them and remains the
                    # single-transaction boundary for custom.
                    if dry_run:
                        await session.rollback()
                    else:
                        await session.commit()
                        committed.append(source)

            if dry_run:
                click.echo(
                    "\n🔎 --dry-run: each source rolled back, nothing saved."
                )
            else:
                done = ", ".join(committed) if committed else "nothing"
                click.echo(f"\n💾 Committed: {done}.")

            # Fresh session, so this reports *committed* state only. Under
            # --dry-run that is the pre-existing table contents, not this
            # run's rolled-back work -- the per-source counts above are the
            # authoritative dry-run output.
            async with db.async_session() as session:
                summary = await session.execute(
                    text(
                        "SELECT source, count(*) FROM aois "
                        "GROUP BY source ORDER BY source"
                    )
                )
                click.echo("\n📊 aois by source (committed):")
                for src, cnt in summary.all():
                    click.echo(f"   {src}: {cnt}")
                links_total = await session.execute(
                    text("SELECT count(*) FROM user_aois")
                )
                click.echo(f"   user_aois: {links_total.scalar()}")

            # Refresh the planner statistics. After a bulk insert the planner
            # has no statistics for the new rows until autoanalyze runs, and
            # until then it does not use the indexes on aois. Skipped under
            # --dry-run, which rolls every source back.
            if committed:
                async with db.async_session() as session:
                    await session.execute(text("ANALYZE aois"))
                    await session.execute(text("ANALYZE user_aois"))
                    await session.commit()
                click.echo("\n📈 Planner statistics refreshed.")
        except Exception:
            if committed:
                click.echo(
                    "\n⚠️  Committed before the failure: "
                    f"{', '.join(committed)}. build-aois is idempotent -- "
                    "re-run to resume."
                )
            raise
        finally:
            await db.close()

    asyncio.run(_inspect() if inspect else _run())


if __name__ == "__main__":
    cli()
