"""The async-specific guarantees: slow password hashing doesn't stall other requests, and
simultaneous logins are all served."""

import asyncio

import pytest

from app.core import security
from app.modules.auth.models import RoleName
from app.modules.auth.tests.helpers import API, PASSWORD

pytestmark = pytest.mark.asyncio


async def test_password_hashing_does_not_block_the_event_loop():
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.001)

    task = asyncio.create_task(ticker())
    await security.hash_password("some-long-password")  # tens of milliseconds of Argon2
    task.cancel()

    assert ticks > 3  # other coroutines kept running while the hash was computed


async def test_simultaneous_logins_all_succeed(client, make_user):
    users = [await make_user(RoleName.STUDENT) for _ in range(6)]

    responses = await asyncio.gather(
        *(client.post(f"{API}/auth/login", data={"username": u.username, "password": PASSWORD}) for u in users)
    )

    assert [r.status_code for r in responses] == [200] * len(users)
