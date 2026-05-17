"""Optional async database (SQLAlchemy). Initialized in app lifespan when DATABASE_URL is set."""

from collections.abc import AsyncGenerator
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_async_engine = None
_async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None


def init_database(database_url: str) -> None:
    global _async_engine, _async_session_maker
    if not database_url:
        return
    _async_engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )
    _async_session_maker = async_sessionmaker(
        _async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def close_database() -> None:
    global _async_engine, _async_session_maker
    if _async_engine is not None:
        await _async_engine.dispose()
    _async_engine = None
    _async_session_maker = None


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    if _async_session_maker is None:
        raise RuntimeError("Database not configured (DATABASE_URL missing).")
    async with _async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
