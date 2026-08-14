"""
Unit tests for shared.db.session.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from shared.db.session import (
    create_db_engine,
    create_session_factory,
    ping_database,
    DatabaseSessionManager,
)


def test_create_db_engine_url_normalization():
    # Standard postgresql:// scheme
    engine = create_db_engine("postgresql://user:pass@localhost:5432/db")
    assert engine.url.drivername == "postgresql+asyncpg"

    # Already asyncpg
    engine_async = create_db_engine("postgresql+asyncpg://user:pass@localhost:5432/db")
    assert engine_async.url.drivername == "postgresql+asyncpg"


def test_create_session_factory():
    engine = create_db_engine("postgresql+asyncpg://user:pass@localhost:5432/db")
    factory = create_session_factory(engine)
    assert callable(factory)


def test_session_manager_uninitialized_error():
    manager = DatabaseSessionManager()
    with pytest.raises(RuntimeError, match="not been initialized"):
        _ = manager.engine

    with pytest.raises(RuntimeError, match="not been initialized"):
        _ = manager.session_factory


@pytest.mark.asyncio
async def test_session_manager_init_and_close():
    manager = DatabaseSessionManager("postgresql+asyncpg://user:pass@localhost:5432/db")
    assert isinstance(manager.engine, AsyncEngine)
    assert callable(manager.session_factory)

    await manager.close()
    with pytest.raises(RuntimeError):
        _ = manager.engine


@pytest.mark.asyncio
async def test_session_manager_get_session_uninitialized():
    manager = DatabaseSessionManager()
    with pytest.raises(RuntimeError, match="is not initialized"):
        async for _ in manager.get_session():
            pass


@pytest.mark.asyncio
async def test_session_manager_get_session_lifecycle():
    manager = DatabaseSessionManager("postgresql+asyncpg://user:pass@localhost:5432/db")
    mock_session = AsyncMock(spec=AsyncSession)

    class MockContextManager:
        async def __aenter__(self):
            return mock_session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    manager._session_factory = MagicMock(return_value=MockContextManager())

    # Normal success commit
    async for s in manager.get_session():
        assert s == mock_session
    assert mock_session.commit.called

    # Rollback on exception thrown into generator
    mock_session.reset_mock()
    gen = manager.get_session()
    s = await anext(gen)
    assert s == mock_session
    with pytest.raises(ValueError, match="fail inside session"):
        await gen.athrow(ValueError("fail inside session"))
    assert mock_session.rollback.called


@pytest.mark.asyncio
async def test_ping_database_success():
    mock_engine = MagicMock(spec=AsyncEngine)
    mock_conn = AsyncMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    res = await ping_database(mock_engine, max_retries=2, initial_backoff=0.01)
    assert res is True
    assert mock_conn.execute.called


@pytest.mark.asyncio
async def test_ping_database_failure_retries():
    mock_engine = MagicMock(spec=AsyncEngine)
    mock_engine.connect.side_effect = Exception("Connection refused")

    with pytest.raises(Exception, match="Connection refused"):
        await ping_database(mock_engine, max_retries=2, initial_backoff=0.01)
