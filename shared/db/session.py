"""
Async database engine, session factory, and connection lifecycle management for RT-FADS.
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

logger = logging.getLogger(__name__)


def create_db_engine(
    database_url: str,
    pool_size: int = 20,
    max_overflow: int = 10,
    pool_timeout: float = 30.0,
    pool_pre_ping: bool = True,
    echo: bool = False,
) -> AsyncEngine:
    """
    Create a production-ready asynchronous SQLAlchemy engine with connection pooling.
    Handles postgresql:// to postgresql+asyncpg:// normalization if necessary.
    """
    normalized_url = database_url
    if normalized_url.startswith("postgresql://"):
        normalized_url = normalized_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql+asyncpg://", 1)

    return create_async_engine(
        normalized_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=pool_pre_ping,
        echo=echo,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async sessionmaker factory bound to the provided engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def ping_database(
    target: "AsyncEngine | DatabaseSessionManager",
    max_retries: int = 5,
    initial_backoff: float = 1.0,
) -> bool:
    """
    Verify database connectivity with exponential backoff.
    Used during service startup to guarantee dependency readiness.
    """
    engine = target.engine if isinstance(target, DatabaseSessionManager) else target
    backoff = initial_backoff
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info(f"Database connection verified on attempt {attempt}/{max_retries}.")
            return True
        except Exception as exc:
            logger.warning(
                f"Database ping failed (attempt {attempt}/{max_retries}): {exc}. Retrying in {backoff:.1f}s..."
            )
            if attempt == max_retries:
                logger.error("Database connection could not be established after maximum retries.")
                raise
            await asyncio.sleep(backoff)
            backoff *= 2.0
    return False


class DatabaseSessionManager:
    """
    Contextual session manager for dependency injection across FastAPI and background workers.
    """

    def __init__(self, database_url: Optional[str] = None):
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        if database_url:
            self.init(database_url)

    def init(self, database_url: str, **kwargs) -> None:
        """Initialize engine and session factory with database URL."""
        self._engine = create_db_engine(database_url, **kwargs)
        self._session_factory = create_session_factory(self._engine)

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("DatabaseSessionManager has not been initialized with a database URL.")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("DatabaseSessionManager has not been initialized with a database URL.")
        return self._session_factory

    async def close(self) -> None:
        """Dispose database engine pool."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Async generator yielding an active session with automatic commit / rollback."""
        if self._session_factory is None:
            raise RuntimeError("DatabaseSessionManager is not initialized.")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise


_session_manager = DatabaseSessionManager()


def get_session_manager() -> DatabaseSessionManager:
    """Returns global DatabaseSessionManager instance."""
    return _session_manager


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    async for session in _session_manager.get_session():
        yield session

