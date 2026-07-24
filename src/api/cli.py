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
"""

import asyncio
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

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
from src.shared.config import SharedSettings
from src.shared.geocoding_helpers import (
    GADM_LEVELS,
    GADM_STANDARD_ID_RE,
    SOURCE_ID_MAPPING,
    _antimeridian_bbox_sql,
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


# ---------------------------------------------------------------------------
# build-aois: populate the unified `aois` / `user_aois` tables
# ---------------------------------------------------------------------------

# Reference sources first, custom last (custom depends only on custom_areas).
_BUILD_SOURCES = ["gadm", "kba", "wdpa", "landmark", "custom"]

# Note: `aois.properties` (JSONB) is intentionally left NULL by this transform.
# It exists as an escape hatch for user-uploaded custom-AOI attributes (needs
# the PR2 API change to accept them) and source-specific reference columns
# (a deliberate follow-up); neither is populated in PR1.

# Which source column carries the ISO3 country code(s), per reference source.
# Resolved case-insensitively at runtime: geometries_* are built by GeoPandas
# `to_postgis` and preserve the source file's (often upper-case) column casing.
_ISO3_SOURCE_COLUMNS = {
    "gadm": ["GID_0"],
    "kba": ["ISO3"],
    "wdpa": ["iso3"],
    "landmark": ["iso_code"],
}


def _multipolygon_sql(geom_expr: str, *, only_if_invalid: bool = False) -> str:
    """Normalize *geom_expr* to a valid 2D MultiPolygon (for the typed column).

    ``ST_MakeValid`` repairs self-intersections / ring errors;
    ``ST_CollectionExtract(..., 3)`` keeps only polygonal parts (dropping the
    line/point slivers ``ST_MakeValid`` can emit); ``ST_Multi`` guarantees the
    ``MULTIPOLYGON`` type the ``aois.geometry`` column enforces. Callers filter
    out an empty result (a geometry with no areal component) with
    ``NOT ST_IsEmpty(...)`` so such rows are skipped, not stored empty.

    ``only_if_invalid`` gates the repair behind ``ST_IsValid``: ``ST_MakeValid``
    is the expensive step (on huge, dense polygons it can allocate enough to get
    the backend OOM-killed) and is a no-op on already-valid input, so skipping
    it there is output-equivalent and spares the common path -- including big
    but valid geometries. It references *geom_expr* three times, so only pass it
    when *geom_expr* is a cheap column read, not a subquery.
    """
    force2d = f"ST_Force2D({geom_expr})"
    core = (
        f"CASE WHEN ST_IsValid({force2d}) THEN {force2d} "
        f"ELSE ST_MakeValid({force2d}) END"
        if only_if_invalid
        else f"ST_MakeValid({force2d})"
    )
    return f"ST_Multi(ST_CollectionExtract({core}, 3))"


def _bbox_float_array_sql(geom_expr: str) -> str:
    """A ``float8[]`` ``[west, south, east, north]`` for *geom_expr*.

    Wraps the shared antimeridian-aware bbox (which yields a JSON array) and
    turns it into a real Postgres array so it lands in ``aois.bbox`` directly.
    ``WITH ORDINALITY`` pins the element order.
    """
    return (
        "(SELECT array_agg(e::double precision ORDER BY ord) "
        f"FROM json_array_elements_text({_antimeridian_bbox_sql(geom_expr)}) "
        "WITH ORDINALITY AS t(e, ord))"
    )


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
    single geometry -- a lone million-vertex polygon can still exhaust the
    backend; that is the job of ``only_if_invalid`` (skip the repair on valid
    input) and the ``MATERIALIZED`` CTE (compute each shape once), with
    simplification of the genuine monsters handled separately.
    """
    cfg = SOURCE_ID_MAPPING[source]
    table, id_col = cfg["table"], cfg["id_column"]

    iso3_col = await _resolve_column(
        session, table, _ISO3_SOURCE_COLUMNS[source]
    )
    iso3_expr = (
        f"string_to_array(NULLIF(btrim(\"{iso3_col}\"::text), ''), ';')"
        if iso3_col
        else "NULL::text[]"
    )

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
    else:
        admin_expr = "NULL::smallint"
        disputed_expr = "false"

    # Normalize source geometry to a valid MultiPolygon once, then derive
    # geometry / bbox / area_km2 from the same shape. only_if_invalid skips the
    # costly ST_MakeValid on already-valid rows (safe: geometry is a column).
    norm_geom = _multipolygon_sql("geometry", only_if_invalid=True)
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
                name,
                subtype,
                {norm_geom} AS geom,
                {iso3_expr} AS iso3,
                {admin_expr} AS admin_level,
                {disputed_expr} AS is_disputed
            FROM {table}
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
            {_bbox_float_array_sql("geom")},
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
            text(sql), {"nchunks": nchunks, "chunk": chunk}
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

    A diagnostic to size up before building: ``ST_NPoints`` only counts
    coordinates (one deserialize per row, freed immediately -- no
    ``ST_MakeValid``-style blowup), and ``ST_GeometryType`` is cheap, so this is
    safe to run on tables that a full transform cannot survive. Surfaces the
    vertex distribution that drives the simplification threshold.
    """
    cfg = SOURCE_ID_MAPPING[source]
    table, id_col = cfg["table"], cfg["id_column"]

    rows, distinct_ids, null_geom, max_pts, avg_pts, gt100k, gt500k, gt1m = (
        await session.execute(
            text(
                f'SELECT count(*), count(DISTINCT CAST("{id_col}" AS TEXT)), '
                "count(*) FILTER (WHERE geometry IS NULL), "
                "max(ST_NPoints(geometry)), "
                "round(avg(ST_NPoints(geometry))), "
                "count(*) FILTER (WHERE ST_NPoints(geometry) > 100000), "
                "count(*) FILTER (WHERE ST_NPoints(geometry) > 500000), "
                "count(*) FILTER (WHERE ST_NPoints(geometry) > 1000000) "
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

    types = await session.execute(
        text(
            f"SELECT ST_GeometryType(geometry), count(*) FROM {table} "
            "WHERE geometry IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
        )
    )
    click.echo("   geometry types:")
    for gtype, cnt in types.all():
        click.echo(f"     {gtype}: {cnt}")


async def _build_custom_aois(session: AsyncSession) -> int:
    """Transform ``custom_areas`` into ``aois`` + one ``owner`` link each.

    Geometry is the dissolved union of the stored GeoJSON-string list, coerced
    to a valid MultiPolygon: overlapping user-drawn parts merge (so ``area_km2``
    is not double-counted) and the result satisfies the typed column. Each area
    gets exactly one ``owner`` row in ``user_aois`` for its ``user_id``. Returns
    the owner-link upsert count.
    """
    # Union dissolves overlapping parts; _multipolygon_sql makes it a valid
    # MultiPolygon. ST_MakeValid per element guards invalid input polygons.
    geom_sql = _multipolygon_sql(
        "(SELECT ST_Union("
        "ST_MakeValid(ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(g), 4326)))"
        ") FROM jsonb_array_elements_text(ca.geometries) AS g)"
    )
    sql = f"""
        WITH collected AS (
            SELECT
                ca.id,
                ca.user_id,
                ca.name,
                ca.created_at,
                ca.updated_at,
                {geom_sql} AS geom
            FROM custom_areas ca
        ),
        ins AS (
            INSERT INTO aois (
                source, source_id, name, subtype, geometry,
                bbox, area_km2, created_by, created_at, updated_at
            )
            SELECT
                'custom',
                id::text,
                name,
                'custom-area',
                geom,
                {_bbox_float_array_sql("geom")},
                ST_Area(geom::geography) / 1e6,
                user_id,
                created_at,
                updated_at
            FROM collected
            WHERE name IS NOT NULL AND geom IS NOT NULL AND NOT ST_IsEmpty(geom)
            ON CONFLICT (source, source_id) WHERE NOT is_deprecated
            DO UPDATE SET
                name = EXCLUDED.name,
                geometry = EXCLUDED.geometry,
                bbox = EXCLUDED.bbox,
                area_km2 = EXCLUDED.area_km2,
                updated_at = now()
            RETURNING id AS aoi_id, created_by AS user_id
        )
        INSERT INTO user_aois (user_id, aoi_id, relationship)
        SELECT user_id, aoi_id, 'owner' FROM ins
        ON CONFLICT (user_id, aoi_id, relationship) DO NOTHING
    """
    result = await session.execute(text(sql))

    # Surface (don't silently drop) custom areas whose geometries couldn't be
    # coerced to a non-empty MultiPolygon.
    skipped = await session.scalar(
        text(
            f"SELECT count(*) FROM custom_areas ca "
            f"WHERE ca.name IS NOT NULL "
            f"AND ({geom_sql} IS NULL OR ST_IsEmpty({geom_sql}))"
        )
    )
    if skipped:
        click.echo(
            f"⚠️  custom: {skipped} area(s) skipped "
            f"(geometries not coercible to a non-empty MultiPolygon)."
        )
    return result.rowcount


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
def build_aois_command(
    sources: tuple, dry_run: bool, chunks: int, inspect: bool
):
    """Populate the unified aois/user_aois tables from already-loaded data.

    Idempotent, set-based, in-DB transform of the reference geometries_*
    tables and custom_areas into the unified schema. Run post-deploy (heavy
    work must not run in the blocking migrate Job). Purely additive: the live
    API keeps serving from geometries_* / custom_areas until the API PR.
    """
    selected = list(sources) or _BUILD_SOURCES
    outcome = "would be upserted" if dry_run else "upserted"

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
                    table = SOURCE_ID_MAPPING[source]["table"]
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
                    table = (
                        "custom_areas"
                        if source == "custom"
                        else SOURCE_ID_MAPPING[source]["table"]
                    )
                    if not await _table_exists(session, table):
                        click.echo(
                            f"⏭️  {source}: {table} not found, skipping."
                        )
                        continue

                    if source == "custom":
                        links = await _build_custom_aois(session)
                        click.echo(
                            f"✅ custom: {links} owner link(s) {outcome}."
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
