"""
The suite runs against a real Postgres, not SQLite.

The models now lean on Postgres-only features — JSONB, ARRAY, and a generated
`tsvector` column with a GIN index. SQLite can't express any of them, so a
SQLite suite would pass while telling you nothing about the code that actually
ships. Requires `docker compose up -d db`.
"""

import os
from collections.abc import AsyncGenerator

import pytest

# Settings are read at import time, so the environment has to be ready first
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5434/dnd")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-validation")
os.environ.setdefault("ENVIRONMENT", "local")

import asyncpg  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

TEST_DB_NAME = "dnd_test"


def _url_for(database: str) -> str:
    base = str(settings.DATABASE_URL)
    return base.rsplit("/", 1)[0] + f"/{database}"


async def _ensure_test_database() -> None:
    """CREATE DATABASE can't run inside a transaction, so it goes through a raw
    asyncpg connection to the maintenance database."""
    dsn = _url_for("postgres").replace("postgresql+asyncpg://", "postgresql://")
    connection = await asyncpg.connect(dsn)

    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
async def engine():
    await _ensure_test_database()

    engine = create_async_engine(_url_for(TEST_DB_NAME), poolclass=NullPool)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Each test runs inside a transaction that is rolled back, so tests can't
    see each other's rows and the schema is only built once."""
    connection = await engine.connect()
    transaction = await connection.begin()
    maker = async_sessionmaker(bind=connection, class_=AsyncSession, expire_on_commit=False)

    async with maker() as session:
        yield session

    await transaction.rollback()
    await connection.close()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield session
        # No commit: the fixture's outer transaction is the unit of work, and
        # rolling it back is what isolates the test.
        await session.flush()

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
