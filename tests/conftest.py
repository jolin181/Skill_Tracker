"""
tests/conftest.py
------------------
Shared fixtures for all tests.

Provides database fixtures compatible with existing project test patterns.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.database import Base, create_engine_for, get_db
from app.main import app as fastapi_app
from app.modules.auth.service import ensure_roles

BASE_URL = "http://testserver"

# All tables for domain analytics tests
TEST_TABLES = [
    "users", "roles", "user_roles", "refresh_tokens",
    "departments", "academic_years", "students",
    "tracks", "levels", "topics", "subtopics",
    "enrollments", "level_progress", "progression_decisions",
    "assessments", "attempts", "results", "topic_results",
    "exam_sessions", "proctoring_events",
    "attempt_answers", "questions", "question_options",
    "student_performance_summary", "domain_performance_summary",
    "semester_progress_summary", "topic_gap_summary",
    "difficulty_performance_summary",
    "domain_incharge", "audit_log"
]

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL and not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must name a database ending in '_test'")


@pytest_asyncio.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """Create test database engine with all required tables."""
    url = TEST_DATABASE_URL or f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    test_engine = create_engine_for(url)

    # Get tables that exist in metadata
    tables = [
        Base.metadata.tables[name]
        for name in TEST_TABLES
        if name in Base.metadata.tables
    ]

    async with test_engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.drop_all(sync, tables=tables))
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))

    yield test_engine
    await test_engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create session factory for test database."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def db_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Database session for arranging test data and checking results."""
    async with session_factory() as session:
        await ensure_roles(session)
        await session.commit()
        yield session


@pytest_asyncio.fixture
async def client(session_factory: async_sessionmaker[AsyncSession], db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Test HTTP client with database dependency override."""
    async def _get_test_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = _get_test_db
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url=BASE_URL) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()
