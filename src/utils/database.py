"""
Database connection management for Project Zeno.

This module provides unified database connection pooling for the entire application,
including API endpoints, tools, and related operations. This eliminates connection
pool fragmentation and prevents connection exhaustion.
"""

import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.utils.config import APISettings
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# Global database engine instance
_global_engine: Optional[AsyncEngine] = None
_global_session_maker: Optional[async_sessionmaker] = None
_engine_lock = asyncio.Lock()


async def initialize_global_pool(database_url: Optional[str] = None) -> None:
    """
    Initialize the global database connection pool.

    This should be called once during application startup.

    Args:
        database_url: Optional database URL override. Uses APISettings.database_url if not provided.
    """
    global _global_engine, _global_session_maker

    async with _engine_lock:
        if _global_engine is not None:
            logger.warning("Global database pool already initialized")
            return

        db_url = database_url or APISettings.database_url

        # Create engine with NullPool since PgBouncer handles connection pooling
        _global_engine = create_async_engine(
            db_url,
            # Use NullPool - no application-level pooling, rely on PgBouncer
            poolclass=NullPool,
            # Disable prepared statements for PgBouncer compatibility
            connect_args={"statement_cache_size": 0},
            # Logging and debugging
            echo=False,  # Set to True for SQL debugging
        )

        # Create session factory
        _global_session_maker = async_sessionmaker(
            _global_engine, expire_on_commit=False, class_=AsyncSession
        )

        logger.info(
            "Global database engine initialized with NullPool - using PgBouncer for connection pooling"
        )


async def close_global_pool() -> None:
    """
    Close the global database engine.

    This should be called during application shutdown.
    """
    global _global_engine, _global_session_maker

    async with _engine_lock:
        if _global_engine is None:
            logger.warning("Global database pool not initialized")
            return

        await _global_engine.dispose()
        _global_engine = None
        _global_session_maker = None

        logger.info("Global database engine closed")


def get_global_engine() -> AsyncEngine:
    """
    Get the global database engine instance.

    Returns:
        The global AsyncEngine instance

    Raises:
        RuntimeError: If the global pool has not been initialized
    """
    if _global_engine is None:
        raise RuntimeError(
            "Global database pool not initialized. Call initialize_global_pool() first."
        )
    return _global_engine


def get_connection_from_pool() -> AsyncConnection:
    """
    Get a database connection from the global engine.

    This is intended for tool operations that need direct SQL access.
    Use as an async context manager to ensure proper cleanup:

    ```python
    async with get_connection_from_pool() as conn:
        result = await conn.execute(text("SELECT 1"))
    ```

    Returns:
        AsyncConnection from the global engine

    Raises:
        RuntimeError: If the global engine has not been initialized
    """
    engine = get_global_engine()
    return engine.connect()


def get_global_session_maker() -> async_sessionmaker:
    """
    Get the global session maker for ORM operations.

    Returns:
        The global async_sessionmaker instance

    Raises:
        RuntimeError: If the global pool has not been initialized
    """
    if _global_session_maker is None:
        raise RuntimeError(
            "Global database pool not initialized. Call initialize_global_pool() first."
        )
    return _global_session_maker


def get_session_from_pool():
    """
    Get a database session context manager from the global engine.

    This function returns a context manager that must be used with 'async with'.
    This ensures proper session lifecycle management and connection cleanup.

    ```python
    async with get_session_from_pool() as session:
        result = await session.execute(select(UserOrm))
        await session.commit()
    ```

    Returns:
        AsyncSession context manager from the global engine

    Raises:
        RuntimeError: If the global engine has not been initialized
    """
    session_maker = get_global_session_maker()
    return session_maker()


async def get_session_from_pool_dependency():
    """
    FastAPI dependency that provides a database session from the global engine.

    This function yields a session and ensures proper cleanup.
    Use this with Depends() in FastAPI route handlers:

    ```python
    async def my_endpoint(session: AsyncSession = Depends(get_session_from_pool_dependency)):
        result = await session.execute(select(UserOrm))
    ```

    Yields:
        AsyncSession from the global engine

    Raises:
        RuntimeError: If the global engine has not been initialized
    """
    async with get_session_from_pool() as session:
        yield session
