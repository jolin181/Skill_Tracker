import pytest

from app.modules.auth.models import RoleName
from app.modules.auth.tests.helpers import API, PASSWORD, bearer

pytestmark = pytest.mark.asyncio

LOGIN = f"{API}/auth/login"
ME = f"{API}/auth/me"
CHANGE = f"{API}/auth/change-password"
NEW_PASSWORD = "Brand-New-Pass-1"


async def test_change_password(client, make_user, login):
    await make_user(username="meena")
    old_token = await login("meena")

    wrong = await client.post(
        CHANGE, headers=bearer(old_token), json={"current_password": "nope", "new_password": NEW_PASSWORD}
    )
    assert wrong.status_code == 400
    assert wrong.json()["code"] == "INVALID_CURRENT_PASSWORD"

    response = await client.post(
        CHANGE, headers=bearer(old_token), json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 200
    new_token = response.json()["access_token"]

    assert (await client.get(ME, headers=bearer(old_token))).json()["code"] == "TOKEN_REVOKED"  # other sessions end
    assert (await client.get(ME, headers=bearer(new_token))).status_code == 200  # this one continues
    assert (await client.post(LOGIN, data={"username": "meena", "password": PASSWORD})).status_code == 401
    assert (await client.post(LOGIN, data={"username": "meena", "password": NEW_PASSWORD})).status_code == 200


async def test_new_password_cannot_be_the_register_number(client, make_user, login):
    student = await make_user(username="meena")
    token = await login("meena")
    response = await client.post(
        CHANGE,
        headers=bearer(token),
        json={"current_password": PASSWORD, "new_password": student.student.reg_num},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "WEAK_PASSWORD"


async def test_new_password_must_be_different_and_long_enough(client, make_user, login):
    await make_user(username="meena")
    token = await login("meena")
    for new_password in (PASSWORD, "short"):
        response = await client.post(
            CHANGE, headers=bearer(token), json={"current_password": PASSWORD, "new_password": new_password}
        )
        assert response.status_code == 422


async def test_staff_created_by_admin_must_change_the_temporary_password_first(client, make_user, login):
    await make_user(RoleName.ADMIN, username="principal")
    admin_token = await login("principal")
    created = await client.post(
        f"{API}/users",
        headers=bearer(admin_token),
        json={
            "username": "ravi",
            "email": "ravi@college.edu",
            "full_name": "Ravi S",
            "roles": ["cyber_domain_owner"],
        },
    )
    assert created.status_code == 201, created.text
    temporary_password = created.json()["temporary_password"]
    assert temporary_password

    first_login = await client.post(LOGIN, data={"username": "ravi", "password": temporary_password})
    assert first_login.json()["user"]["must_change_password"] is True
    token = first_login.json()["access_token"]

    assert (await client.get(ME, headers=bearer(token))).status_code == 200  # can see who they are
    blocked = await client.patch(ME, headers=bearer(token), json={"phone": "9876543210"})
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    changed = await client.post(
        CHANGE, headers=bearer(token), json={"current_password": temporary_password, "new_password": NEW_PASSWORD}
    )
    assert changed.status_code == 200
    assert changed.json()["user"]["must_change_password"] is False
    new_token = changed.json()["access_token"]
    assert (await client.patch(ME, headers=bearer(new_token), json={"phone": "9876543210"})).status_code == 200


async def test_users_can_update_their_phone_only(client, make_user, login):
    await make_user(username="meena")
    token = await login("meena")

    response = await client.patch(
        ME, headers=bearer(token), json={"phone": "+91 90000 11111", "full_name": "Someone Else"}
    )

    assert response.status_code == 200
    assert response.json()["phone"] == "+919000011111"
    assert response.json()["full_name"] != "Someone Else"  # ignored: only admins change names
