"""Fixtures for the auth and users tests.

By default every test gets a fresh SQLite database file (no server needed). To run the same
tests against PostgreSQL, set TEST_DATABASE_URL to a database whose name ends in _test, e.g.

    TEST_DATABASE_URL=postgresql+asyncpg://skill_user:skill_pass@localhost:5432/skill_leveling_test

The tables are dropped and recreated for every test, so tests never see each other's data.
Each API request gets its own session, like in production. The users module's tests reuse
these fixtures (see app/modules/users/tests/conftest.py).
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import security
from app.core.database import Base, create_engine_for, get_db
from app.main import app as fastapi_app
from app.modules.auth.models import RoleName
from app.modules.auth.service import ensure_roles, get_roles, new_user, set_user_roles
from app.modules.auth.tests.helpers import API, PASSWORD
from app.modules.domains.models import Track
from app.modules.users.models import Department, DomainIncharge, Student, User

BASE_URL = "http://testserver"

# Only the tables auth and users use, so other modules' models can't affect these tests.
AUTH_TABLES = (
    "users",
    "roles",
    "user_roles",
    "refresh_tokens",
    "departments",
    "academic_years",
    "students",
    "tracks",
    "domain_incharge",
    "audit_log",
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL and not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must name a database ending in '_test': the tests drop every table.")


@pytest_asyncio.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    url = TEST_DATABASE_URL or f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    test_engine = create_engine_for(url)
    tables = [Base.metadata.tables[name] for name in AUTH_TABLES]
    async with test_engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.drop_all(sync, tables=tables))
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """The test's own session, for arranging data and checking results."""
    async with session_factory() as session:
        await ensure_roles(session)
        await session.commit()
        yield session


@pytest_asyncio.fixture
async def client(session_factory: async_sessionmaker[AsyncSession], db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _get_test_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = _get_test_db
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url=BASE_URL) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def new_client(client: AsyncClient) -> Callable[..., AsyncClient]:
    """A second browser: new_client(cookies={...}). Use it in `async with`."""

    def _make(**kwargs: object) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url=BASE_URL, **kwargs)  # type: ignore[arg-type]

    return _make


@pytest_asyncio.fixture
async def department(db: AsyncSession) -> Department:
    dept = Department(code="CSE", name="Computer Science and Engineering")
    db.add(dept)
    await db.commit()
    return dept


async def _make_track(db: AsyncSession, name: str, owner_role: RoleName | None) -> Track:
    item = Track(name=name, is_active=True)
    db.add(item)
    await db.flush()
    if owner_role is not None:
        (role,) = await get_roles(db, [owner_role])
        role.track_id = item.id
    await db.commit()
    return item


@pytest_asyncio.fixture
async def track(db: AsyncSession) -> Track:
    """Full Stack Development, linked to the fullstack_domain_owner role."""
    return await _make_track(db, "Full Stack Development", RoleName.FULLSTACK_DOMAIN_OWNER)


@pytest_asyncio.fixture
async def other_track(db: AsyncSession) -> Track:
    """Machine Learning, linked to the ml_domain_owner role."""
    return await _make_track(db, "Machine Learning", RoleName.ML_DOMAIN_OWNER)


@pytest_asyncio.fixture
async def unlinked_track(db: AsyncSession) -> Track:
    """A track no role is linked to yet."""
    return await _make_track(db, "Cyber Security", None)


@pytest.fixture
def make_user(db: AsyncSession, department: Department) -> Callable[..., Awaitable[User]]:
    """await make_user(RoleName.FULLSTACK_DOMAIN_OWNER, tracks=[track]) -> a saved user whose
    password is PASSWORD. Pass several roles with roles=[...]."""
    counter = iter(range(1, 100_000))

    async def _make(
        role: RoleName = RoleName.STUDENT,
        *,
        roles: list[RoleName] | None = None,
        username: str | None = None,
        password: str = PASSWORD,
        is_active: bool = True,
        must_change_password: bool = False,
        tracks: tuple[Track, ...] | list[Track] = (),
    ) -> User:
        n = next(counter)
        roles = roles or [role]
        username = username or f"{roles[0].value}{n}"
        user = new_user(
            username=username,
            email=f"{username}@college.edu",
            full_name=f"Test User {n}",
            password_hash=await security.hash_password(password),
            is_active=is_active,
            must_change_password=must_change_password,
        )
        set_user_roles(user, await get_roles(db, roles))
        if RoleName.STUDENT in roles:
            user.student = Student(reg_num=f"3123{n:08d}", department=department, curr_sem=3)
        for item in tracks:
            user.track_assignments.append(DomainIncharge(track=item, emp_id=f"EMP{n:03d}"))
        db.add(user)
        await db.commit()
        return user

    return _make


@pytest.fixture
def login(client: AsyncClient) -> Callable[..., Awaitable[str]]:
    """await login("username") -> access token. The refresh cookie lands in the client's cookie jar."""

    async def _login(identifier: str, password: str = PASSWORD, *, using: AsyncClient | None = None) -> str:
        response = await (using or client).post(
            f"{API}/auth/login", data={"username": identifier, "password": password}
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    return _login
