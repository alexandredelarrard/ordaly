from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.database import get_async_session


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: async DB session (requires ``DATABASE_URL``)."""
    async for session in get_async_session():
        yield session
