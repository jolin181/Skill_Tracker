import base64
import json
from datetime import timedelta

import jwt
import pytest
from sqlalchemy import select, update

from app.core import security
from app.core.config import settings
from app.modules.auth.models import RefreshToken, RoleName
from app.modules.auth.tests.helpers import API, PASSWORD, bearer
from app.utils.time_utils import utcnow

pytestmark = pytest.mark.asyncio

LOGIN = f"{API}/auth/login"
REFRESH = f"{API}/auth/refresh"
LOGOUT = f"{API}/auth/logout"
LOGOUT_ALL = f"{API}/auth/logout-all"
ME = f"{API}/auth/me"


# ------------------------------------------------------------------ login


async def test_login_returns_access_token_and_sets_refresh_cookie(client, make_user):
    user = await make_user(username="meena")

    response = await client.post(LOGIN, data={"username": "meena", "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_expire_minutes * 60
    assert body["user"]["id"] == user.id
    assert body["user"]["roles"] == ["student"]
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["sub"] == str(user.id)
    assert claims["roles"] == ["student"]

    cookie = response.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie
    assert "httponly" in cookie
    assert f"path={settings.refresh_cookie_path}" in cookie
    assert f"samesite={settings.cookie_samesite}" in cookie


async def test_login_with_email(client, make_user):
    user = await make_user(username="meena")
    response = await client.post(LOGIN, data={"username": user.email.upper(), "password": PASSWORD})
    assert response.status_code == 200


async def test_token_carries_every_role_the_user_holds(client, make_user):
    await make_user(roles=[RoleName.ML_DOMAIN_OWNER, RoleName.CYBER_DOMAIN_OWNER], username="dual")
    body = (await client.post(LOGIN, data={"username": "dual", "password": PASSWORD})).json()

    assert body["user"]["roles"] == ["cyber_domain_owner", "ml_domain_owner"]
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["roles"] == ["cyber_domain_owner", "ml_domain_owner"]


async def test_wrong_password_and_unknown_user_get_the_same_answer(client, make_user):
    await make_user(username="meena")

    wrong_password = await client.post(LOGIN, data={"username": "meena", "password": "not-my-password"})
    unknown_user = await client.post(LOGIN, data={"username": "nobody", "password": "not-my-password"})

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["code"] == "INVALID_CREDENTIALS"


async def test_account_locks_after_repeated_wrong_passwords(client, make_user, db):
    user = await make_user(username="meena")
    for _ in range(settings.login_max_failed_attempts - 1):
        response = await client.post(LOGIN, data={"username": "meena", "password": "wrong-password"})
        assert response.status_code == 401

    locking_attempt = await client.post(LOGIN, data={"username": "meena", "password": "wrong-password"})
    assert locking_attempt.status_code == 429
    assert locking_attempt.json()["code"] == "ACCOUNT_LOCKED"
    assert int(locking_attempt.headers["retry-after"]) > 0

    # While locked, even the right password is refused.
    assert (await client.post(LOGIN, data={"username": "meena", "password": PASSWORD})).status_code == 429

    # Once the lock runs out, the right password works again.
    user.locked_until = utcnow() - timedelta(seconds=1)
    await db.commit()
    assert (await client.post(LOGIN, data={"username": "meena", "password": PASSWORD})).status_code == 200


async def test_deactivated_account_cannot_log_in(client, make_user):
    await make_user(username="meena", is_active=False)
    response = await client.post(LOGIN, data={"username": "meena", "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_DISABLED"


# ------------------------------------------------------------------ access tokens


async def test_protected_route_needs_a_token(client):
    response = await client.get(ME)
    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_returns_the_logged_in_user(client, make_user, login):
    user = await make_user(username="meena")
    body = (await client.get(ME, headers=bearer(await login("meena")))).json()
    assert body["id"] == user.id
    assert body["roles"] == ["student"]
    assert body["student"]["curr_sem"] == 3
    assert body["student"]["year"] == 2
    assert body["student"]["department"]["code"] == "CSE"
    assert body["track_assignments"] == []


async def test_edited_token_is_rejected(client, make_user, login):
    """A student can't make themselves admin by editing the token: the signature no longer matches."""
    await make_user(username="meena")
    header, payload, signature = (await login("meena")).split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["roles"] = ["admin"]
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    response = await client.get(ME, headers=bearer(f"{header}.{forged_payload}.{signature}"))

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


async def test_token_signed_with_another_key_or_no_algorithm_is_rejected(client, make_user):
    user = await make_user(username="meena")
    claims = {"sub": str(user.id), "ver": 0, "type": "access", "iat": utcnow(), "exp": utcnow() + timedelta(minutes=5)}
    other_key = jwt.encode(claims, "some-other-secret-key-that-is-long-enough-1234", algorithm="HS256")
    unsigned = jwt.encode(claims, None, algorithm="none")

    for token in (other_key, unsigned, "not-a-jwt"):
        response = await client.get(ME, headers=bearer(token))
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_TOKEN"


async def test_expired_token_is_rejected(client, make_user, login, monkeypatch):
    await make_user(username="meena")
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    response = await client.get(ME, headers=bearer(await login("meena")))
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


# ------------------------------------------------------------------ refresh tokens


async def test_refresh_gives_new_tokens_and_replaces_the_cookie(client, make_user, login):
    await make_user(username="meena")
    await login("meena")
    first_cookie = client.cookies.get("refresh_token")

    response = await client.post(REFRESH)

    assert response.status_code == 200
    new_cookie = client.cookies.get("refresh_token")
    assert new_cookie and new_cookie != first_cookie
    assert (await client.get(ME, headers=bearer(response.json()["access_token"]))).status_code == 200


async def test_refresh_token_is_stored_only_as_a_hash(client, make_user, login, db):
    await make_user(username="meena")
    await login("meena")
    raw = client.cookies.get("refresh_token")

    stored = (await db.scalars(select(RefreshToken.token_hash))).all()

    assert raw not in stored
    assert security.hash_token(raw) in stored


async def test_refresh_without_cookie_is_rejected(client):
    response = await client.post(REFRESH)
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_TOKEN_MISSING"


async def test_reused_refresh_token_ends_the_session(client, make_user, login, db, new_client):
    """If an old refresh token is used again (e.g. it was stolen), the whole session is revoked."""
    await make_user(username="meena")
    access_token = await login("meena")
    stolen = client.cookies.get("refresh_token")
    assert (await client.post(REFRESH)).status_code == 200  # the real user refreshes
    # Pretend that refresh happened a minute ago, outside the grace window for parallel tabs.
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == security.hash_token(stolen))
        .values(revoked_at=utcnow() - timedelta(minutes=1))
    )
    await db.commit()

    async with new_client(cookies={"refresh_token": stolen}) as attacker:
        attempt = await attacker.post(REFRESH)

    assert attempt.status_code == 401
    assert attempt.json()["code"] == "INVALID_REFRESH_TOKEN"
    # The real user's newer refresh token and their access token are revoked too.
    assert (await client.post(REFRESH)).status_code == 401
    assert (await client.get(ME, headers=bearer(access_token))).json()["code"] == "TOKEN_REVOKED"


async def test_two_tabs_refreshing_at_the_same_time_both_succeed(client, make_user, login, new_client):
    await make_user(username="meena")
    await login("meena")
    shared_cookie = client.cookies.get("refresh_token")
    assert (await client.post(REFRESH)).status_code == 200  # tab 1

    async with new_client(cookies={"refresh_token": shared_cookie}) as tab_two:
        assert (await tab_two.post(REFRESH)).status_code == 200  # tab 2, a moment later, same old cookie

    assert (await client.post(REFRESH)).status_code == 200


async def test_refresh_is_refused_from_a_foreign_website(client, make_user, login):
    await make_user(username="meena")
    await login("meena")

    foreign = await client.post(REFRESH, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    assert foreign.json()["code"] == "BAD_ORIGIN"

    frontend = await client.post(REFRESH, headers={"Origin": settings.allowed_origins[0]})
    assert frontend.status_code == 200


async def test_cors_allows_the_frontend_with_credentials(client):
    origin = settings.allowed_origins[0]
    response = await client.options(REFRESH, headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


# ------------------------------------------------------------------ logout


async def test_logout_ends_this_session_and_clears_the_cookie(client, make_user, login, new_client):
    await make_user(username="meena")
    await login("meena")
    cookie = client.cookies.get("refresh_token")

    response = await client.post(LOGOUT)

    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    async with new_client(cookies={"refresh_token": cookie}) as other:
        assert (await other.post(REFRESH)).status_code == 401


async def test_logout_all_ends_every_session(client, make_user, login, new_client):
    await make_user(username="meena")
    phone_token = await login("meena")
    async with new_client() as laptop:
        laptop_token = await login("meena", using=laptop)

        assert (await client.post(LOGOUT_ALL, headers=bearer(phone_token))).status_code == 204

        assert (await client.get(ME, headers=bearer(phone_token))).json()["code"] == "TOKEN_REVOKED"
        assert (await laptop.get(ME, headers=bearer(laptop_token))).status_code == 401
        assert (await laptop.post(REFRESH)).status_code == 401
