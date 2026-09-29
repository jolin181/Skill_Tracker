"""The roles schema (roles + user_roles, no role column on users), the permission checks, and the
dict-returning dependencies the other modules use. Throwaway routes show how modules use them."""

import uuid

import pytest
from fastapi import APIRouter, Depends
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.core.audit import AuditLog, write_audit_log
from app.core.database import Base
from app.core.dependencies import (
    DomainOwnerOrAdmin,
    TrackManager,
    get_current_user,
    require_admin,
    require_roles,
    require_student,
)
from app.main import app as fastapi_app
from app.modules.auth.models import DOMAIN_OWNER_ROLES, Role, RoleName, UserRole
from app.modules.auth.tests.helpers import API, bearer

pytestmark = pytest.mark.asyncio

probe = APIRouter(prefix="/_test")


@probe.get("/tracks/{track_id}/manage")
async def manage_track(track_id: int, user: TrackManager) -> dict[str, int]:
    return {"track_id": track_id, "user_id": user.id}


@probe.get("/domain-owners")
async def domain_owners_only(user: DomainOwnerOrAdmin) -> dict[str, int]:
    return {"user_id": user.id}


@probe.get("/ml-only", dependencies=[Depends(require_roles(RoleName.ML_DOMAIN_OWNER))])
async def ml_only() -> dict[str, bool]:
    return {"ok": True}


# The same shapes the slots / allocation / secret_code / hall_sheets routers use.
@probe.get("/legacy/admin")
async def legacy_admin(current_admin: dict = Depends(require_admin)) -> dict:
    return {"id": current_admin["id"], "roles": current_admin["roles"], "has_user": current_admin["user"] is not None}


@probe.get("/legacy/student")
async def legacy_student(current_student: dict = Depends(require_student)) -> dict:
    return {"id": current_student["id"], "roles": current_student["roles"]}


@probe.get("/legacy/me")
async def legacy_me(current_user: dict = Depends(get_current_user)) -> dict:
    return {"id": current_user["id"], "roles": current_user["roles"]}


fastapi_app.include_router(probe)


# ------------------------------------------------------------------ schema


async def test_users_table_has_no_role_column():
    columns = set(Base.metadata.tables["users"].columns.keys())
    assert not {"role", "roles", "role_id"} & columns


async def test_roles_table_has_a_track_link():
    table = Base.metadata.tables["roles"]
    assert table.columns["track_id"].nullable
    assert {fk.target_fullname for fk in table.columns["track_id"].foreign_keys} == {"tracks.id"}


async def test_user_roles_links_users_to_roles():
    table = Base.metadata.tables["user_roles"]
    assert {fk.target_fullname for fk in table.foreign_keys} == {"users.id", "roles.id"}


async def test_exactly_the_six_roles_exist(db):
    names = set(await db.scalars(select(Role.name)))
    assert names == {
        "admin",
        "student",
        "fullstack_domain_owner",
        "cyber_domain_owner",
        "cloud_devops_domain_owner",
        "ml_domain_owner",
    }


async def test_the_same_role_cannot_be_given_twice(db, make_user):
    user = await make_user(RoleName.ADMIN)
    admin_role_id = await db.scalar(select(Role.id).where(Role.name == "admin"))
    with pytest.raises(IntegrityError):  # unique (user_id, role_id)
        await db.execute(insert(UserRole).values(user_id=user.id, role_id=admin_role_id))
    await db.rollback()


async def test_only_domain_owner_roles_can_have_a_track(db, track):
    """The database refuses it too, not just the API (CHECK constraint on roles)."""
    (admin_role,) = await db.scalars(select(Role).where(Role.name == "admin"))
    admin_role.track_id = track.id
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_roles_endpoint_lists_all_roles(client, make_user, login):
    admin = await make_user(RoleName.ADMIN)
    response = await client.get(f"{API}/roles", headers=bearer(await login(admin.username)))
    assert response.status_code == 200
    assert len(response.json()) == 6


# ------------------------------------------------------------------ dict dependencies (compatibility)


async def test_legacy_dependencies_still_return_the_same_dict(client, make_user, login):
    admin = await make_user(RoleName.ADMIN)
    student = await make_user(RoleName.STUDENT)
    admin_token = await login(admin.username)
    student_token = await login(student.username)

    body = (await client.get("/_test/legacy/admin", headers=bearer(admin_token))).json()
    assert body == {"id": admin.id, "roles": ["admin"], "has_user": True}
    assert (await client.get("/_test/legacy/student", headers=bearer(student_token))).json() == {
        "id": student.id,
        "roles": ["student"],
    }
    assert (await client.get("/_test/legacy/me", headers=bearer(student_token))).json()["id"] == student.id


async def test_legacy_dependencies_enforce_roles(client, make_user, login):
    student_token = await login((await make_user(RoleName.STUDENT)).username)
    owner_token = await login((await make_user(RoleName.ML_DOMAIN_OWNER)).username)

    assert (await client.get("/_test/legacy/admin", headers=bearer(student_token))).status_code == 403
    assert (await client.get("/_test/legacy/student", headers=bearer(owner_token))).status_code == 403
    assert (await client.get("/_test/legacy/admin")).status_code == 401


async def test_write_audit_log_accepts_the_secret_code_call(db, make_user):
    """secret_code calls write_audit_log(db, action=..., actor_user_id=<uuid or int>, details=...)."""
    admin = await make_user(RoleName.ADMIN)
    await write_audit_log(db, action="SECRET_CODE_REVEALED", actor_user_id=admin.id, details={"entity_id": "1"})
    await write_audit_log(db, action="SECRET_CODE_REVEALED", actor_user_id=uuid.uuid4(), details={"entity_id": "2"})
    await db.commit()

    entries = list(await db.scalars(select(AuditLog).where(AuditLog.action == "SECRET_CODE_REVEALED").order_by(AuditLog.id)))
    assert [e.actor_user_id for e in entries] == [admin.id, None]
    assert "actor" in entries[1].details  # a non-integer id is kept in details


# ------------------------------------------------------------------ role checks


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (RoleName.STUDENT, 403),
        (RoleName.FULLSTACK_DOMAIN_OWNER, 403),
        (RoleName.CYBER_DOMAIN_OWNER, 403),
        (RoleName.CLOUD_DEVOPS_DOMAIN_OWNER, 403),
        (RoleName.ML_DOMAIN_OWNER, 403),
        (RoleName.ADMIN, 200),
    ],
)
async def test_only_admins_can_manage_users(client, make_user, login, role, expected):
    user = await make_user(role)
    response = await client.get(f"{API}/users", headers=bearer(await login(user.username)))
    assert response.status_code == expected
    if expected == 403:
        assert response.json()["code"] == "INSUFFICIENT_ROLE"


@pytest.mark.parametrize("role", sorted(DOMAIN_OWNER_ROLES | {RoleName.ADMIN}))
async def test_every_domain_owner_role_and_admin_pass_the_domain_owner_check(client, make_user, login, role):
    user = await make_user(role)
    assert (await client.get("/_test/domain-owners", headers=bearer(await login(user.username)))).status_code == 200


async def test_students_fail_the_domain_owner_check(client, make_user, login):
    user = await make_user(RoleName.STUDENT)
    assert (await client.get("/_test/domain-owners", headers=bearer(await login(user.username)))).status_code == 403


async def test_a_specific_domain_role_can_be_required(client, make_user, login):
    ml_owner = await make_user(RoleName.ML_DOMAIN_OWNER)
    cyber_owner = await make_user(RoleName.CYBER_DOMAIN_OWNER)
    assert (await client.get("/_test/ml-only", headers=bearer(await login(ml_owner.username)))).status_code == 200
    assert (await client.get("/_test/ml-only", headers=bearer(await login(cyber_owner.username)))).status_code == 403


async def test_a_user_with_several_roles_passes_each_of_their_checks(client, make_user, login):
    user = await make_user(roles=[RoleName.ADMIN, RoleName.ML_DOMAIN_OWNER])
    token = await login(user.username)
    assert (await client.get("/_test/ml-only", headers=bearer(token))).status_code == 200
    assert (await client.get(f"{API}/users", headers=bearer(token))).status_code == 200


# ------------------------------------------------------------------ track scoping (roles.track_id)


async def test_domain_owner_can_only_manage_their_roles_track(client, make_user, login, track, other_track):
    owner = await make_user(RoleName.FULLSTACK_DOMAIN_OWNER)  # no domain_incharge row needed
    token = await login(owner.username)

    assert (await client.get(f"/_test/tracks/{track.id}/manage", headers=bearer(token))).status_code == 200
    denied = await client.get(f"/_test/tracks/{other_track.id}/manage", headers=bearer(token))
    assert denied.status_code == 403
    assert denied.json()["code"] == "NOT_TRACK_OWNER"


async def test_owned_tracks_are_reported_to_the_frontend(client, make_user, login, track, other_track):
    owner = await make_user(roles=[RoleName.FULLSTACK_DOMAIN_OWNER, RoleName.ML_DOMAIN_OWNER])
    body = (await client.get(f"{API}/auth/me", headers=bearer(await login(owner.username)))).json()
    assert body["owned_track_ids"] == sorted([track.id, other_track.id])


async def test_owner_of_an_unlinked_role_manages_nothing(client, make_user, login, track, unlinked_track):
    owner = await make_user(RoleName.CYBER_DOMAIN_OWNER)  # cyber role isn't linked to a track yet
    token = await login(owner.username)
    for item in (track, unlinked_track):
        assert (await client.get(f"/_test/tracks/{item.id}/manage", headers=bearer(token))).status_code == 403


async def test_linking_a_role_takes_effect_on_the_next_request(client, make_user, login, unlinked_track):
    admin_headers = bearer(await login((await make_user(RoleName.ADMIN)).username))
    owner = await make_user(RoleName.CYBER_DOMAIN_OWNER)
    owner_token = await login(owner.username)
    url = f"/_test/tracks/{unlinked_track.id}/manage"
    assert (await client.get(url, headers=bearer(owner_token))).status_code == 403

    roles = {r["name"]: r for r in (await client.get(f"{API}/roles", headers=admin_headers)).json()}
    linked = await client.patch(
        f"{API}/roles/{roles['cyber_domain_owner']['id']}", headers=admin_headers, json={"track_id": unlinked_track.id}
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["track_id"] == unlinked_track.id

    assert (await client.get(url, headers=bearer(owner_token))).status_code == 200  # same token, no re-login


async def test_a_track_belongs_to_only_one_role(client, make_user, login, track):
    admin_headers = bearer(await login((await make_user(RoleName.ADMIN)).username))
    roles = {r["name"]: r for r in (await client.get(f"{API}/roles", headers=admin_headers)).json()}

    taken = await client.patch(
        f"{API}/roles/{roles['cyber_domain_owner']['id']}", headers=admin_headers, json={"track_id": track.id}
    )
    assert taken.status_code == 409
    assert taken.json()["code"] == "TRACK_ALREADY_LINKED"

    not_domain = await client.patch(f"{API}/roles/{roles['admin']['id']}", headers=admin_headers, json={"track_id": track.id})
    assert not_domain.status_code == 400
    assert not_domain.json()["code"] == "NOT_A_DOMAIN_OWNER_ROLE"

    unknown = await client.patch(
        f"{API}/roles/{roles['cyber_domain_owner']['id']}", headers=admin_headers, json={"track_id": 999999}
    )
    assert unknown.json()["code"] == "TRACK_NOT_FOUND"


async def test_moving_a_role_to_another_track_moves_its_owners(client, make_user, login, track, unlinked_track):
    admin_headers = bearer(await login((await make_user(RoleName.ADMIN)).username))
    owner = await make_user(RoleName.FULLSTACK_DOMAIN_OWNER, tracks=[track])
    roles = {r["name"]: r for r in (await client.get(f"{API}/roles", headers=admin_headers)).json()}

    moved = await client.patch(
        f"{API}/roles/{roles['fullstack_domain_owner']['id']}", headers=admin_headers, json={"track_id": unlinked_track.id}
    )
    assert moved.status_code == 200

    token = await login(owner.username)
    assert (await client.get(f"/_test/tracks/{track.id}/manage", headers=bearer(token))).status_code == 403
    assert (await client.get(f"/_test/tracks/{unlinked_track.id}/manage", headers=bearer(token))).status_code == 200
    # The assignment to the old track is gone.
    details = (await client.get(f"{API}/users/{owner.id}", headers=admin_headers)).json()
    assert details["track_assignments"] == []


async def test_admin_can_manage_every_track(client, make_user, login, track, other_track):
    admin = await make_user(RoleName.ADMIN)
    token = await login(admin.username)
    for item in (track, other_track):
        assert (await client.get(f"/_test/tracks/{item.id}/manage", headers=bearer(token))).status_code == 200


async def test_a_domain_owner_role_check_alone_does_not_grant_other_tracks(client, make_user, login, other_track):
    """DomainOwnerOrAdmin only says "some domain owner"; routes about one track must use TrackManager."""
    owner = await make_user(RoleName.FULLSTACK_DOMAIN_OWNER)
    token = await login(owner.username)
    assert (await client.get("/_test/domain-owners", headers=bearer(token))).status_code == 200
    assert (await client.get(f"/_test/tracks/{other_track.id}/manage", headers=bearer(token))).status_code == 403


async def test_students_cannot_manage_tracks(client, make_user, login, track):
    user = await make_user(RoleName.STUDENT)
    response = await client.get(f"/_test/tracks/{track.id}/manage", headers=bearer(await login(user.username)))
    assert response.status_code == 403


async def test_role_change_applies_immediately(client, make_user, login, track, other_track):
    """Roles come from the database on every request, and changing them ends old sessions."""
    admin = await make_user(RoleName.ADMIN)
    owner = await make_user(RoleName.FULLSTACK_DOMAIN_OWNER, tracks=[track])
    admin_token = await login(admin.username)
    owner_token = await login(owner.username)

    response = await client.patch(
        f"{API}/users/{owner.id}", headers=bearer(admin_token), json={"roles": ["ml_domain_owner"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["ml_domain_owner"]
    assert response.json()["track_assignments"] == []  # the Full Stack assignment no longer fits

    assert (await client.get(f"/_test/tracks/{track.id}/manage", headers=bearer(owner_token))).status_code == 401
    new_token = await login(owner.username)
    assert (await client.get("/_test/ml-only", headers=bearer(new_token))).status_code == 200
    # Now limited to the ML track instead of Full Stack.
    assert (await client.get(f"/_test/tracks/{track.id}/manage", headers=bearer(new_token))).status_code == 403
    assert (await client.get(f"/_test/tracks/{other_track.id}/manage", headers=bearer(new_token))).status_code == 200
