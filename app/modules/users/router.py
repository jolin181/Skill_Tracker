"""
app/modules/users/router.py
---------------------------
Admin-only account management (/users), the role list and role→track links (/roles),
departments (/departments) and the audit log (/audit-logs).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import AdminUser, Client, DbSession, require_admin
from app.modules.auth.models import RoleName
from app.modules.users import service as user_service
from app.modules.users.schemas import (
    AdminCreateUserRequest,
    AdminCreateUserResponse,
    AdminUpdateUserRequest,
    AdminUserOut,
    AuditLogOut,
    DepartmentCreate,
    DepartmentOut,
    Page,
    RoleOut,
    RoleUpdateRequest,
    StudentProfileUpdateRequest,
    TemporaryPasswordResponse,
    TrackAssignRequest,
)

# The router-level dependency guards every route, even one added later without a role check.
router = APIRouter(prefix="/users", tags=["Users (admin)"], dependencies=[Depends(require_admin)])
roles_router = APIRouter(prefix="/roles", tags=["Users (admin)"], dependencies=[Depends(require_admin)])
audit_router = APIRouter(prefix="/audit-logs", tags=["Users (admin)"], dependencies=[Depends(require_admin)])
departments_router = APIRouter(prefix="/departments", tags=["Departments"])


@router.get("", response_model=Page[AdminUserOut])
async def list_users(
    db: DbSession,
    role: RoleName | None = None,
    is_active: bool | None = None,
    department_id: int | None = None,
    curr_sem: Annotated[int | None, Query(ge=1, le=10)] = None,
    q: Annotated[str | None, Query(max_length=100, description="Search name, username, email, reg/roll no")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AdminUserOut]:
    users, total = await user_service.list_users(
        db,
        role=role,
        is_active=is_active,
        department_id=department_id,
        curr_sem=curr_sem,
        q=q,
        limit=limit,
        offset=offset,
    )
    return Page[AdminUserOut](
        items=[AdminUserOut.model_validate(u) for u in users], total=total, limit=limit, offset=offset
    )


@router.post("", response_model=AdminCreateUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: AdminCreateUserRequest, admin: AdminUser, db: DbSession, client: Client
) -> AdminCreateUserResponse:
    """Create a staff account (admin and/or domain owner roles).

    Without a password, a temporary one is generated and returned once. Either way the user
    must change it at first login.
    """
    user, temporary_password = await user_service.create_staff_user(db, data, admin, client)
    return AdminCreateUserResponse(user=AdminUserOut.model_validate(user), temporary_password=temporary_password)


@router.get("/{user_id}", response_model=AdminUserOut)
async def get_user(user_id: int, db: DbSession) -> AdminUserOut:
    return AdminUserOut.model_validate(await user_service.get_user(db, user_id))


@router.patch("/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: int, data: AdminUpdateUserRequest, admin: AdminUser, db: DbSession, client: Client
) -> AdminUserOut:
    """Change name, email, phone or roles. `roles` replaces the whole set (staff accounts only),
    logs the user out everywhere, and removes assignments to tracks the new roles don't cover."""
    return AdminUserOut.model_validate(await user_service.update_user(db, user_id, data, admin, client))


@router.patch("/{user_id}/student-profile", response_model=AdminUserOut)
async def update_student_profile(
    user_id: int, data: StudentProfileUpdateRequest, admin: AdminUser, db: DbSession, client: Client
) -> AdminUserOut:
    return AdminUserOut.model_validate(await user_service.update_student_profile(db, user_id, data, admin, client))


@router.post("/{user_id}/deactivate", response_model=AdminUserOut)
async def deactivate_user(user_id: int, admin: AdminUser, db: DbSession, client: Client) -> AdminUserOut:
    """Blocks login and ends all sessions immediately. Nothing is deleted."""
    return AdminUserOut.model_validate(await user_service.set_active(db, user_id, False, admin, client))


@router.post("/{user_id}/activate", response_model=AdminUserOut)
async def activate_user(user_id: int, admin: AdminUser, db: DbSession, client: Client) -> AdminUserOut:
    return AdminUserOut.model_validate(await user_service.set_active(db, user_id, True, admin, client))


@router.post("/{user_id}/reset-password", response_model=TemporaryPasswordResponse)
async def reset_password(user_id: int, admin: AdminUser, db: DbSession, client: Client) -> TemporaryPasswordResponse:
    """Generates a temporary password (shown once) and ends the user's sessions."""
    return TemporaryPasswordResponse(temporary_password=await user_service.reset_password(db, user_id, admin, client))


@router.post("/{user_id}/unlock", response_model=AdminUserOut)
async def unlock_user(user_id: int, admin: AdminUser, db: DbSession, client: Client) -> AdminUserOut:
    """Clear a lockout caused by too many wrong passwords."""
    return AdminUserOut.model_validate(await user_service.unlock_user(db, user_id, admin, client))


@router.post("/{user_id}/tracks", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def assign_track(
    user_id: int, data: TrackAssignRequest, admin: AdminUser, db: DbSession, client: Client
) -> AdminUserOut:
    """Record a domain owner's assignment to their role's track (adds a domain_incharge row)."""
    user = await user_service.assign_track(db, user_id, data.track_id, data.emp_id, admin, client)
    return AdminUserOut.model_validate(user)


@router.delete("/{user_id}/tracks/{track_id}", response_model=AdminUserOut)
async def unassign_track(
    user_id: int, track_id: int, admin: AdminUser, db: DbSession, client: Client
) -> AdminUserOut:
    return AdminUserOut.model_validate(await user_service.unassign_track(db, user_id, track_id, admin, client))


@roles_router.get("", response_model=list[RoleOut])
async def list_roles(db: DbSession) -> list[RoleOut]:
    return [RoleOut.model_validate(r) for r in await user_service.list_roles(db)]


@roles_router.patch("/{role_id}", response_model=RoleOut)
async def set_role_track(
    role_id: int, data: RoleUpdateRequest, admin: AdminUser, db: DbSession, client: Client
) -> RoleOut:
    """Link a domain-owner role to the track its holders manage (`null` unlinks it).
    Each track can belong to only one role."""
    return RoleOut.model_validate(await user_service.set_role_track(db, role_id, data.track_id, admin, client))


@audit_router.get("", response_model=Page[AuditLogOut])
async def list_audit_logs(
    db: DbSession,
    action: str | None = None,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditLogOut]:
    entries, total = await user_service.list_audit_logs(
        db, action=action, actor_user_id=actor_user_id, target_user_id=target_user_id, limit=limit, offset=offset
    )
    return Page[AuditLogOut](
        items=[AuditLogOut.model_validate(e) for e in entries], total=total, limit=limit, offset=offset
    )


@departments_router.get("", response_model=list[DepartmentOut])
async def list_departments(db: DbSession) -> list[DepartmentOut]:
    """Public, because the registration form needs it before anyone is logged in."""
    return [DepartmentOut.model_validate(d) for d in await user_service.list_departments(db)]


@departments_router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(data: DepartmentCreate, admin: AdminUser, db: DbSession, client: Client) -> DepartmentOut:
    return DepartmentOut.model_validate(await user_service.create_department(db, data, admin, client))
