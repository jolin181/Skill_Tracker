"""
app/modules/users/service.py
----------------------------
Account management for admins, plus departments, roles and the audit log. The routers make sure
only admins get here; every change is written to the audit log in the same transaction.

Role rules:
- A student account holds exactly the `student` role, and never a staff role.
- A staff account holds one or more of: admin, fullstack/cyber/cloud_devops/ml domain owner.
- Each domain-owner role is linked to one track (roles.track_id). Its holders may manage only
  that track, and may only be assigned (domain_incharge) to that track.
- Changing someone's roles logs them out everywhere and removes their assignments to tracks
  the new roles don't cover.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.audit import AuditAction, AuditLog, record
from app.core.exceptions import BadRequest, Conflict, NotFound
from app.core.integrity import flush_or_conflict
from app.modules.auth.models import DOMAIN_OWNER_ROLES, RevokeReason, Role, RoleName, UserRole
from app.modules.auth.service import (
    ClientInfo,
    get_roles,
    get_user_with_details,
    invalidate_all_sessions,
    new_user,
    set_user_roles,
)
from app.modules.domains.models import Track
from app.modules.users.models import USER_DETAIL_OPTIONS, AcademicYear, Department, DomainIncharge, Student, User
from app.modules.users.schemas import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    DepartmentCreate,
    StudentProfileUpdateRequest,
)


async def list_users(
    db: AsyncSession,
    *,
    role: RoleName | None = None,
    is_active: bool | None = None,
    department_id: int | None = None,
    curr_sem: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    conditions: list[Any] = []
    if role is not None:
        holders = select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.name == role)
        conditions.append(User.id.in_(holders))
    if is_active is not None:
        conditions.append(User.is_active == is_active)
    if department_id is not None:
        conditions.append(Student.department_id == department_id)
    if curr_sem is not None:
        conditions.append(Student.curr_sem == curr_sem)
    if q and q.strip():
        term = q.strip()
        conditions.append(
            or_(
                User.username.icontains(term, autoescape=True),
                User.email.icontains(term, autoescape=True),
                User.full_name.icontains(term, autoescape=True),
                Student.reg_num.icontains(term, autoescape=True),
                Student.roll_number.icontains(term, autoescape=True),
            )
        )
    query = select(User).outerjoin(Student, Student.user_id == User.id).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = await db.scalars(query.options(*USER_DETAIL_OPTIONS).order_by(User.id).limit(limit).offset(offset))
    return list(users), total


async def get_user(db: AsyncSession, user_id: int) -> User:
    user = await get_user_with_details(db, user_id)
    if user is None:
        raise NotFound("USER_NOT_FOUND", "User not found.")
    return user


async def create_staff_user(
    db: AsyncSession, data: AdminCreateUserRequest, admin: User, client: ClientInfo
) -> tuple[User, str | None]:
    """Returns the new user and, if no password was given, the generated temporary password."""
    if data.password:
        initial_password, temporary_password = data.password, None
    else:
        initial_password = temporary_password = security.generate_temporary_password()
    user = new_user(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        phone=data.phone,
        password_hash=await security.hash_password(initial_password),
        must_change_password=True,  # the admin knows this password, so the user must replace it
    )
    roles = await get_roles(db, data.roles)
    set_user_roles(user, roles)
    tracks = await _get_tracks(db, data.track_ids)
    _check_tracks_match_roles([track.id for track in tracks], roles)
    for track in tracks:
        user.track_assignments.append(DomainIncharge(track=track, emp_id=data.emp_id))
    db.add(user)
    await flush_or_conflict(db)

    record(
        db,
        AuditAction.USER_CREATED,
        actor_id=admin.id,
        target_id=user.id,
        details={"roles": [str(r) for r in data.roles], "track_ids": sorted(set(data.track_ids))},
        ip=client.ip,
    )
    await db.commit()
    return await get_user(db, user.id), temporary_password


async def update_user(
    db: AsyncSession, user_id: int, data: AdminUpdateUserRequest, admin: User, client: ClientInfo
) -> User:
    user = await get_user(db, user_id)
    changes: dict[str, Any] = {}
    for field in ("full_name", "email", "phone"):
        if field in data.model_fields_set and getattr(data, field) != getattr(user, field):
            changes[field] = [getattr(user, field), getattr(data, field)]
            setattr(user, field, getattr(data, field))
    if "roles" in data.model_fields_set and data.roles is not None and set(data.roles) != user.role_set:
        await _change_roles(db, user, data.roles, admin, changes)
    if not changes:
        return user

    await flush_or_conflict(db)
    record(db, AuditAction.USER_UPDATED, actor_id=admin.id, target_id=user.id, details=changes, ip=client.ip)
    await db.commit()
    return await get_user(db, user.id)


async def _change_roles(
    db: AsyncSession, user: User, new_roles: list[RoleName], admin: User, changes: dict[str, Any]
) -> None:
    if user.id == admin.id:
        raise BadRequest("CANNOT_MODIFY_SELF", "You can't change your own roles.")
    if RoleName.STUDENT in user.role_set:
        raise BadRequest(
            "ROLE_CHANGE_NOT_ALLOWED",
            "Student accounts can't become staff accounts. Create a separate account.",
        )
    changes["roles"] = [user.role_names, sorted(str(r) for r in new_roles)]
    roles = await get_roles(db, new_roles)
    # Keep only the assignments for tracks the new roles still cover.
    allowed = _role_track_ids(roles)
    dropped = [a for a in user.track_assignments if a.track_id not in allowed]
    if dropped:
        changes["removed_track_ids"] = [a.track_id for a in dropped]
        for assignment in dropped:
            user.track_assignments.remove(assignment)  # delete-orphan removes the domain_incharge row
    set_user_roles(user, roles)
    await invalidate_all_sessions(db, user, RevokeReason.ROLES_CHANGED)


def _role_track_ids(roles: Iterable[Role]) -> set[int]:
    return {role.track_id for role in roles if role.track_id is not None and role.name in DOMAIN_OWNER_ROLES}


def _check_tracks_match_roles(track_ids: Iterable[int], roles: Iterable[Role]) -> None:
    outside = sorted(set(track_ids) - _role_track_ids(roles))
    if outside:
        raise BadRequest(
            "TRACK_NOT_IN_ROLE",
            f"Track(s) {outside} don't belong to this user's domain-owner roles. "
            "A domain owner can only be assigned the track linked to their role.",
        )


async def update_student_profile(
    db: AsyncSession, user_id: int, data: StudentProfileUpdateRequest, admin: User, client: ClientInfo
) -> User:
    user = await get_user(db, user_id)
    student = user.student
    if student is None:
        raise BadRequest("NOT_A_STUDENT", "This user is not a student.")
    fields = data.model_fields_set

    changes: dict[str, Any] = {}
    if "department_id" in fields and data.department_id != student.department_id:
        department = await db.get(Department, data.department_id)
        if department is None:
            raise BadRequest("DEPARTMENT_NOT_FOUND", "Unknown department.")
        changes["department_id"] = [student.department_id, department.id]
        student.department = department
    if "academic_year_id" in fields and data.academic_year_id != student.academic_year_id:
        if data.academic_year_id is not None and await db.get(AcademicYear, data.academic_year_id) is None:
            raise BadRequest("ACADEMIC_YEAR_NOT_FOUND", "Unknown academic year.")
        changes["academic_year_id"] = [student.academic_year_id, data.academic_year_id]
        student.academic_year_id = data.academic_year_id
    for field in ("reg_num", "roll_number", "curr_sem", "foundation_year_completed"):
        if field in fields and getattr(data, field) != getattr(student, field):
            changes[field] = [getattr(student, field), getattr(data, field)]
            setattr(student, field, getattr(data, field))
    if not changes:
        return user

    await flush_or_conflict(db)
    record(
        db, AuditAction.STUDENT_PROFILE_UPDATED, actor_id=admin.id, target_id=user.id, details=changes, ip=client.ip
    )
    await db.commit()
    return await get_user(db, user.id)


async def set_active(db: AsyncSession, user_id: int, active: bool, admin: User, client: ClientInfo) -> User:
    """Deactivate instead of deleting: attempts, results and certificates still point at the user."""
    user = await get_user(db, user_id)
    if user.id == admin.id:
        raise BadRequest("CANNOT_MODIFY_SELF", "You can't deactivate or reactivate your own account.")
    if user.is_active == active:
        return user
    user.is_active = active
    if not active:
        await invalidate_all_sessions(db, user, RevokeReason.DEACTIVATED)
    action = AuditAction.USER_ACTIVATED if active else AuditAction.USER_DEACTIVATED
    record(db, action, actor_id=admin.id, target_id=user.id, ip=client.ip)
    await db.commit()
    return user


async def reset_password(db: AsyncSession, user_id: int, admin: User, client: ClientInfo) -> str:
    """Set a temporary password (returned to the admin) and log the user out everywhere."""
    user = await get_user(db, user_id)
    if user.id == admin.id:
        raise BadRequest("CANNOT_MODIFY_SELF", "Use change-password for your own account.")
    temporary_password = security.generate_temporary_password()
    user.password_hash = await security.hash_password(temporary_password)
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    await invalidate_all_sessions(db, user, RevokeReason.PASSWORD_RESET)
    record(db, AuditAction.PASSWORD_RESET, actor_id=admin.id, target_id=user.id, ip=client.ip)
    await db.commit()
    return temporary_password


async def unlock_user(db: AsyncSession, user_id: int, admin: User, client: ClientInfo) -> User:
    user = await get_user(db, user_id)
    user.failed_login_count = 0
    user.locked_until = None
    record(db, AuditAction.USER_UNLOCKED, actor_id=admin.id, target_id=user.id, ip=client.ip)
    await db.commit()
    return user


async def assign_track(
    db: AsyncSession, user_id: int, track_id: int, emp_id: str | None, admin: User, client: ClientInfo
) -> User:
    user = await get_user(db, user_id)
    if not user.is_domain_owner:
        raise BadRequest("NOT_A_DOMAIN_OWNER", "Only domain owners can be assigned to tracks.")
    track = await db.get(Track, track_id)
    if track is None:
        raise NotFound("TRACK_NOT_FOUND", "Track not found.")
    _check_tracks_match_roles([track_id], [link.role for link in user.user_roles])
    if any(a.track_id == track_id for a in user.track_assignments):
        raise Conflict("TRACK_ALREADY_ASSIGNED", "This user is already assigned to that track.")
    user.track_assignments.append(DomainIncharge(track=track, emp_id=emp_id))
    await flush_or_conflict(db)
    record(
        db,
        AuditAction.TRACK_ASSIGNED,
        actor_id=admin.id,
        target_id=user.id,
        details={"track_id": track_id},
        ip=client.ip,
    )
    await db.commit()
    return await get_user(db, user.id)


async def unassign_track(db: AsyncSession, user_id: int, track_id: int, admin: User, client: ClientInfo) -> User:
    user = await get_user(db, user_id)
    assignment = next((a for a in user.track_assignments if a.track_id == track_id), None)
    if assignment is None:
        raise NotFound("ASSIGNMENT_NOT_FOUND", "This user is not assigned to that track.")
    user.track_assignments.remove(assignment)  # delete-orphan removes the row
    record(
        db,
        AuditAction.TRACK_UNASSIGNED,
        actor_id=admin.id,
        target_id=user.id,
        details={"track_id": track_id},
        ip=client.ip,
    )
    await db.commit()
    return await get_user(db, user.id)


async def list_roles(db: AsyncSession) -> list[Role]:
    return list(await db.scalars(select(Role).order_by(Role.id)))


async def set_role_track(
    db: AsyncSession, role_id: int, track_id: int | None, admin: User, client: ClientInfo
) -> Role:
    """Link a domain-owner role to its track (or unlink it with None).

    Takes effect on the next request of everyone holding the role, since permission checks read
    roles from the database. Their assignments to the previous track are removed.
    """
    role = await db.get(Role, role_id)
    if role is None:
        raise NotFound("ROLE_NOT_FOUND", "Role not found.")
    if role.name not in DOMAIN_OWNER_ROLES:
        raise BadRequest("NOT_A_DOMAIN_OWNER_ROLE", "Only domain-owner roles are linked to a track.")
    if track_id is not None and await db.get(Track, track_id) is None:
        raise NotFound("TRACK_NOT_FOUND", "Track not found.")
    if role.track_id == track_id:
        return role

    previous = role.track_id
    role.track_id = track_id
    if previous is not None:
        holders = select(UserRole.user_id).where(UserRole.role_id == role.id)
        await db.execute(
            delete(DomainIncharge).where(DomainIncharge.track_id == previous, DomainIncharge.user_id.in_(holders))
        )
    await flush_or_conflict(db)  # a track already linked to another role becomes a 409
    record(
        db,
        AuditAction.ROLE_TRACK_CHANGED,
        actor_id=admin.id,
        details={"role": role.name, "track_id": [previous, track_id]},
        ip=client.ip,
    )
    await db.commit()
    return role


async def list_audit_logs(
    db: AsyncSession,
    *,
    action: str | None = None,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditLog], int]:
    conditions: list[Any] = []
    if action:
        conditions.append(AuditLog.action == action)
    if actor_user_id is not None:
        conditions.append(AuditLog.actor_user_id == actor_user_id)
    if target_user_id is not None:
        conditions.append(AuditLog.target_user_id == target_user_id)
    query = select(AuditLog).where(*conditions)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    entries = await db.scalars(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset))
    return list(entries), total


async def list_departments(db: AsyncSession) -> list[Department]:
    return list(await db.scalars(select(Department).order_by(Department.code, Department.id)))


async def create_department(db: AsyncSession, data: DepartmentCreate, admin: User, client: ClientInfo) -> Department:
    department = Department(code=data.code, name=data.name)
    db.add(department)
    await flush_or_conflict(db)
    record(db, AuditAction.DEPARTMENT_CREATED, actor_id=admin.id, details={"code": department.code}, ip=client.ip)
    await db.commit()
    return department


async def _get_tracks(db: AsyncSession, track_ids: Iterable[int]) -> list[Track]:
    wanted = set(track_ids)
    if not wanted:
        return []
    tracks = list(await db.scalars(select(Track).where(Track.id.in_(wanted)).order_by(Track.id)))
    missing = wanted - {track.id for track in tracks}
    if missing:
        raise BadRequest("TRACK_NOT_FOUND", f"Unknown track id(s): {sorted(missing)}")
    return tracks
