from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


async def get_async_engine(db_url: str) -> AsyncEngine:
    engine = create_async_engine(
        db_url, pool_size=15, max_overflow=5, pool_pre_ping=True
    )
    return engine
