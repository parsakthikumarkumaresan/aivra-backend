"""Shared pytest fixtures.

Tests run against a real Postgres database (``aivra_test``), not sqlite —
pgvector and Postgres-specific constraints must behave the same in tests as
in production. Each test runs inside a transaction that is rolled back,
so tests never leak state into each other despite sharing one schema.

Each test gets its own engine/connection (function scope), deliberately
matching pytest-asyncio's default per-test event loop — a session-scoped
asyncpg connection pool outlives the loop it was opened on and corrupts
under reuse across tests.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.shared.database import session as db_session_module
from app.shared.database.all_models import Base

_ENV_TEST_PATH = Path(__file__).resolve().parent.parent / ".env.test"


def pytest_configure(config: pytest.Config) -> None:
    """Load .env.test before any app module reads settings.

    Must run as the pytest_configure hook (not a module-level side effect)
    so app imports can stay at the top of this file.
    """
    for key, value in dotenv_values(_ENV_TEST_PATH).items():
        if value is not None:
            os.environ[key] = value
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _prepare_schema() -> None:
    async def _create_schema() -> None:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            # Base.metadata.create_all doesn't know about Postgres
            # extensions — the real migration (see migrations/versions/
            # b04ab831f230) creates this explicitly; tests must too.
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_create_schema())


@pytest_asyncio.fixture
async def db_session(_prepare_schema: None) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(get_settings().database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def app(db_session: AsyncSession):
    """The FastAPI app with its DB dependency overridden to the test
    session. Exposed separately from ``client`` so tests can add further
    ``dependency_overrides`` (e.g. swapping in a fake payment provider)
    before making requests.
    """
    from app.main import app as fastapi_app

    async def _get_db_override():
        yield db_session

    fastapi_app.dependency_overrides[db_session_module.get_db] = _get_db_override
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def _isolate_redis_per_test() -> AsyncGenerator[None, None]:
    """Redis-backed rate limiting (app.shared.security.rate_limit) uses a
    real, shared Redis instance whose keys would otherwise persist across
    tests and cause unrelated tests to start hitting 429s. Flush the test
    DB before each test for isolation, matching the DB transaction-rollback
    approach above.

    Also disposes the client connection afterward — it is a module-level
    singleton bound to whichever event loop first created it, and each test
    gets its own event loop (same class of bug as the DB engine above).
    """
    from app.shared.cache.redis_client import dispose_redis, get_redis

    await get_redis().flushdb()
    yield
    await dispose_redis()
