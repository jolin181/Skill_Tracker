from datetime import timedelta

import pytest
import pytest_asyncio

from app.modules.auth.models import RoleName
from app.modules.auth.tests.helpers import API, PASSWORD, bearer
from app.modules.users.models import AcademicYear, Department
from app.utils.time_utils import utcnow

pytestmark = pytest.mark.asyncio

USERS = f"{API}/users"
LOGIN = f"{API}/auth/login"
ME = f"{API}/auth/me"


@pytest_asyncio.fixture
async def admin_headers(make_user, login) -> dict[str, str]:
    admin = await make_user(RoleName.ADMIN, username="principal")
    return bearer(await login(admin.username))


async def test_create_domain_owner_with_tracks(client, admin_headers, track):
    response = await client.post(
        USERS,
        headers=admin_headers,
        json={
            "username": "Priya.R",
            "email": "priya@college.edu",
            "full_name": "Priya R",
            "roles": ["fullstack_domain_owner"],
            "emp_id": "emp042",
            "track_ids": [track.id],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["username"] == "priya.r"
    assert body["user"]["roles"] == ["fullstack_domain_owner"]
    assert body["user"]["must_change_password"] is True
    assert body["user"]["track_assignments"] == [
        {"track_id": track.id, "track_name": "Full Stack Development", "emp_id": "EMP042"}
    ]
    assert len(body["temporary_password"]) >= 12


async def test_create_user_with_several_roles(client, admin_headers):
    response = await client.post(
        USERS,
        headers=admin_headers,
        json={
            "username": "hod",
            "email": "hod@college.edu",
            "full_name": "Head of Dept",
            "roles": ["ml_domain_owner", "admin", "ml_domain_owner"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["user"]["roles"] == ["admin", "ml_domain_owner"]  # sorted, duplicates dropped


async def test_admin_given_password_is_not_echoed_back(client, admin_headers):
    response = await client.post(
        USERS,
        headers=admin_headers,
        json={
            "username": "kavi",
            "email": "kavi@college.edu",
            "full_name": "Kavi",
            "roles": ["admin"],
            "password": "Chosen-Pass-11",
        },
    )
    assert response.status_code == 201
    assert response.json()["temporary_password"] is None
    assert (await client.post(LOGIN, data={"username": "kavi", "password": "Chosen-Pass-11"})).status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"roles": ["student"]},  # students register themselves
        {"roles": ["admin", "student"]},
        {"roles": []},
        {"roles": ["superuser"]},
        {"roles": ["admin"], "track_ids": [1]},  # only domain owners get tracks
    ],
)
async def test_create_user_validation(client, admin_headers, overrides):
    data = {"username": "ravi", "email": "ravi@college.edu", "full_name": "Ravi", **overrides}
    response = await client.post(USERS, headers=admin_headers, json=data)
    assert response.status_code == 422, overrides


async def test_create_domain_owner_with_another_domains_track(client, admin_headers, track):
    data = {
        "username": "ravi",
        "email": "ravi@college.edu",
        "full_name": "Ravi",
        "roles": ["cyber_domain_owner"],
        "track_ids": [track.id],  # the Full Stack track
    }
    response = await client.post(USERS, headers=admin_headers, json=data)
    assert response.status_code == 400
    assert response.json()["code"] == "TRACK_NOT_IN_ROLE"


async def test_create_user_with_unknown_track(client, admin_headers):
    data = {
        "username": "ravi",
        "email": "ravi@college.edu",
        "full_name": "Ravi",
        "roles": ["cyber_domain_owner"],
        "track_ids": [999999],
    }
    response = await client.post(USERS, headers=admin_headers, json=data)
    assert response.status_code == 400
    assert response.json()["code"] == "TRACK_NOT_FOUND"


async def test_list_filter_search_and_paginate(client, admin_headers, make_user):
    first = await make_user(RoleName.STUDENT)
    await make_user(RoleName.STUDENT)
    await make_user(RoleName.CLOUD_DEVOPS_DOMAIN_OWNER)

    students = (await client.get(USERS, headers=admin_headers, params={"role": "student"})).json()
    assert students["total"] == 2
    assert {tuple(u["roles"]) for u in students["items"]} == {("student",)}

    owners = (await client.get(USERS, headers=admin_headers, params={"role": "cloud_devops_domain_owner"})).json()
    assert owners["total"] == 1

    found = (await client.get(USERS, headers=admin_headers, params={"q": first.student.reg_num})).json()
    assert [u["id"] for u in found["items"]] == [first.id]

    page = (await client.get(USERS, headers=admin_headers, params={"limit": 1, "offset": 1})).json()
    assert page["total"] == 4  # 2 students + domain owner + the admin
    assert len(page["items"]) == 1


async def test_deactivate_and_reactivate(client, admin_headers, make_user, login):
    student = await make_user(RoleName.STUDENT)
    student_token = await login(student.username)

    response = await client.post(f"{USERS}/{student.id}/deactivate", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert (await client.get(ME, headers=bearer(student_token))).status_code == 401
    assert (await client.post(LOGIN, data={"username": student.username, "password": PASSWORD})).status_code == 403

    await client.post(f"{USERS}/{student.id}/activate", headers=admin_headers)
    assert await login(student.username)


async def test_admin_cannot_lock_themselves_out(client, make_user, login):
    admin = await make_user(RoleName.ADMIN)
    headers = bearer(await login(admin.username))

    deactivate = await client.post(f"{USERS}/{admin.id}/deactivate", headers=headers)
    demote = await client.patch(f"{USERS}/{admin.id}", headers=headers, json={"roles": ["ml_domain_owner"]})

    assert deactivate.status_code == demote.status_code == 400
    assert deactivate.json()["code"] == demote.json()["code"] == "CANNOT_MODIFY_SELF"


async def test_losing_every_domain_owner_role_removes_tracks(client, admin_headers, make_user, track):
    owner = await make_user(RoleName.FULLSTACK_DOMAIN_OWNER, tracks=[track])

    response = await client.patch(f"{USERS}/{owner.id}", headers=admin_headers, json={"roles": ["admin"]})

    assert response.status_code == 200
    assert response.json()["roles"] == ["admin"]
    assert response.json()["track_assignments"] == []


async def test_adding_a_role_keeps_the_others(client, admin_headers, make_user, track):
    owner = await make_user(RoleName.FULLSTACK_DOMAIN_OWNER, tracks=[track])

    response = await client.patch(
        f"{USERS}/{owner.id}", headers=admin_headers, json={"roles": ["fullstack_domain_owner", "cyber_domain_owner"]}
    )

    assert response.json()["roles"] == ["cyber_domain_owner", "fullstack_domain_owner"]
    assert [a["track_id"] for a in response.json()["track_assignments"]] == [track.id]


async def test_students_cannot_become_staff(client, admin_headers, make_user):
    student = await make_user(RoleName.STUDENT)
    response = await client.patch(f"{USERS}/{student.id}", headers=admin_headers, json={"roles": ["ml_domain_owner"]})
    assert response.status_code == 400
    assert response.json()["code"] == "ROLE_CHANGE_NOT_ALLOWED"


async def test_update_details_and_duplicate_email(client, admin_headers, make_user):
    first = await make_user(RoleName.CYBER_DOMAIN_OWNER)
    second = await make_user(RoleName.CYBER_DOMAIN_OWNER)

    renamed = await client.patch(f"{USERS}/{first.id}", headers=admin_headers, json={"full_name": "Dr. Anitha"})
    assert renamed.json()["full_name"] == "Dr. Anitha"

    clash = await client.patch(f"{USERS}/{first.id}", headers=admin_headers, json={"email": second.email})
    assert clash.status_code == 409
    assert clash.json()["code"] == "EMAIL_TAKEN"

    null_name = await client.patch(f"{USERS}/{first.id}", headers=admin_headers, json={"full_name": None})
    assert null_name.status_code == 422


async def test_reset_password_clears_lockout_and_forces_a_change(client, admin_headers, make_user, db):
    user = await make_user(RoleName.CYBER_DOMAIN_OWNER)
    user.locked_until = utcnow() + timedelta(minutes=5)
    await db.commit()

    reset = await client.post(f"{USERS}/{user.id}/reset-password", headers=admin_headers)
    temporary = reset.json()["temporary_password"]

    response = await client.post(LOGIN, data={"username": user.username, "password": temporary})
    assert response.status_code == 200
    assert response.json()["user"]["must_change_password"] is True


async def test_unlock(client, admin_headers, make_user, db):
    user = await make_user(RoleName.STUDENT)
    user.locked_until = utcnow() + timedelta(minutes=5)
    await db.commit()
    assert (await client.post(LOGIN, data={"username": user.username, "password": PASSWORD})).status_code == 429

    response = await client.post(f"{USERS}/{user.id}/unlock", headers=admin_headers)

    assert response.json()["locked_until"] is None
    assert (await client.post(LOGIN, data={"username": user.username, "password": PASSWORD})).status_code == 200


async def test_update_student_profile(client, admin_headers, make_user, db):
    student = await make_user(RoleName.STUDENT)
    it = Department(code="IT", name="Information Technology")
    year = AcademicYear(label="2026-2027")
    db.add_all([it, year])
    await db.commit()

    response = await client.patch(
        f"{USERS}/{student.id}/student-profile",
        headers=admin_headers,
        json={"department_id": it.id, "academic_year_id": year.id, "curr_sem": 5, "foundation_year_completed": True},
    )
    assert response.status_code == 200, response.text
    profile = response.json()["student"]
    assert (profile["department"]["code"], profile["curr_sem"], profile["year"]) == ("IT", 5, 3)
    assert profile["academic_year_id"] == year.id
    assert profile["foundation_year_completed"] is True

    bad_year = await client.patch(
        f"{USERS}/{student.id}/student-profile", headers=admin_headers, json={"academic_year_id": year.id + 99}
    )
    assert bad_year.status_code == 400
    assert bad_year.json()["code"] == "ACADEMIC_YEAR_NOT_FOUND"

    not_a_student = await make_user(RoleName.ADMIN)
    response = await client.patch(
        f"{USERS}/{not_a_student.id}/student-profile", headers=admin_headers, json={"curr_sem": 4}
    )
    assert response.json()["code"] == "NOT_A_STUDENT"


async def test_assign_and_unassign_tracks(client, admin_headers, make_user, track, other_track):
    owner = await make_user(RoleName.FULLSTACK_DOMAIN_OWNER)
    url = f"{USERS}/{owner.id}/tracks"

    outside_role = await client.post(url, headers=admin_headers, json={"track_id": other_track.id})
    assert outside_role.status_code == 400
    assert outside_role.json()["code"] == "TRACK_NOT_IN_ROLE"

    assigned = await client.post(url, headers=admin_headers, json={"track_id": track.id, "emp_id": "E7"})
    assert assigned.status_code == 201
    assert [a["track_id"] for a in assigned.json()["track_assignments"]] == [track.id]

    again = await client.post(url, headers=admin_headers, json={"track_id": track.id})
    assert again.status_code == 409
    assert again.json()["code"] == "TRACK_ALREADY_ASSIGNED"

    removed = await client.delete(f"{url}/{track.id}", headers=admin_headers)
    assert removed.json()["track_assignments"] == []

    admin_only = await make_user(RoleName.ADMIN)
    wrong_role = await client.post(f"{USERS}/{admin_only.id}/tracks", headers=admin_headers, json={"track_id": track.id})
    assert wrong_role.json()["code"] == "NOT_A_DOMAIN_OWNER"


async def test_unknown_user_is_404(client, admin_headers):
    response = await client.get(f"{USERS}/999999", headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


async def test_admin_actions_are_audited(client, admin_headers, make_user):
    student = await make_user(RoleName.STUDENT)
    await client.post(f"{USERS}/{student.id}/deactivate", headers=admin_headers)

    log = (
        await client.get(f"{API}/audit-logs", headers=admin_headers, params={"target_user_id": student.id})
    ).json()

    assert log["items"][0]["action"] == "admin.user_deactivated"


async def test_departments(client, admin_headers, department, make_user, login):
    assert [d["code"] for d in (await client.get(f"{API}/departments")).json()] == ["CSE"]  # public

    created = await client.post(f"{API}/departments", headers=admin_headers, json={"code": " ece ", "name": "Electronics"})
    assert created.status_code == 201
    assert created.json()["code"] == "ECE"

    duplicate = await client.post(f"{API}/departments", headers=admin_headers, json={"code": "ECE", "name": "Again"})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "DEPARTMENT_CODE_TAKEN"

    student = await make_user(RoleName.STUDENT)
    denied = await client.post(
        f"{API}/departments", headers=bearer(await login(student.username)), json={"code": "X", "name": "X"}
    )
    assert denied.status_code == 403
