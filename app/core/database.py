"""
app/core/database.py
--------------------
Async SQLAlchemy engine and session factory.

Provides:
- `engine`        — async engine instance.
- `AsyncSessionLocal` — async session factory.
- `Base`          — declarative base for all ORM models.
- `UTCDateTime`   — TIMESTAMPTZ column type that always returns timezone-aware UTC datetimes.
- `get_db()`      — FastAPI dependency that yields a database session.

TODO: Add health-check query on startup.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, event
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

from app.core.config import settings


# ── Declarative Base ──────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """Shared declarative base for all ORM models across modules."""
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """TIMESTAMPTZ in PostgreSQL. Always stores and returns timezone-aware UTC datetimes,
    also on SQLite (used by the tests), which would otherwise drop the time zone."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime given for a UTC column; use app.utils.time_utils.utcnow().")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


# ── Engine ────────────────────────────────────────────────────────────────────
def create_engine_for(url: str) -> AsyncEngine:
    """PostgreSQL (asyncpg) in real deployments; SQLite (aiosqlite) is supported for tests."""
    if make_url(url).get_backend_name() == "sqlite":
        sqlite_engine = create_async_engine(url, echo=settings.debug)

        @event.listens_for(sqlite_engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores foreign keys unless asked
            cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block writers
            cursor.close()

        return sqlite_engine

    return create_async_engine(
        url,
        echo=settings.debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,  # drop connections the database (or PgBouncer) closed
        pool_recycle=1800,
        # Work in UTC inside the database; the frontend converts to IST for display.
        connect_args={"server_settings": {"timezone": "UTC"}},
    )


engine = create_engine_for(settings.database_url)

# ── Session Factory ───────────────────────────────────────────────────────────
# expire_on_commit=False: objects stay readable after commit. In async code an expired
# attribute can't be lazy-loaded (it raises MissingGreenlet), so this matters.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ── Dependency ────────────────────────────────────────────────────────────────
async def get_db() -> AsyncIterator[AsyncSession]:
    """
    FastAPI dependency that yields an async DB session. Anything left uncommitted
    is rolled back when the request finishes.
    """
    async with AsyncSessionLocal() as session:
        yield session
