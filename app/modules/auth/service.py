"""
app/modules/auth/service.py
---------------------------
Roles, registration, login, token refresh, logout and password changes (all async).

Every function that changes data also writes its audit entry and commits once, so an action and
its audit entry are stored together or not at all.

Cross-module calls: none. Uses core/ and the users module's models (User, Student, Department).
"""

import logging
import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.audit import AuditAction, record
from app.core.config import settings
from app.core.exceptions import BadRequest, Forbidden, TooManyRequests, Unauthorized
from app.core.integrity import flush_or_conflict
from app.modules.auth.models import RefreshToken, RevokeReason, Role, RoleName, UserRole
from app.modules.auth.schemas import RegisterRequest, UpdateMeRequest
from app.modules.users.models import USER_DETAIL_OPTIONS, AcademicYear, Department, Student, User
from app.utils.time_utils import utcnow

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Incorrect username/email or password."
SESSION_ENDED = "Your session has ended. Please log in again."


@dataclass(frozen=True)
class ClientInfo:
    """Where a request came from. Stored with refresh tokens and audit entries."""

    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class IssuedTokens:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str


# ------------------------------------------------------------------ roles


async def ensure_roles(db: AsyncSession) -> None:
    """Insert any of the six role names that are missing. The migration already does this;
    the tests and the seed script call it too. The caller commits."""
    existing = set(await db.scalars(select(Role.name)))
    db.add_all(Role(name=name) for name in RoleName if name not in existing)
    await db.flush()


async def get_roles(db: AsyncSession, names: Iterable[str]) -> list[Role]:
    wanted = set(names)
    roles = list(await db.scalars(select(Role).where(Role.name.in_(wanted)).order_by(Role.name)))
    missing = wanted - {role.name for role in roles}
    if missing:
        raise RuntimeError(
            f"Role(s) {sorted(missing)} are missing from the roles table. Run the migrations (alembic upgrade head)."
        )
    return roles


def set_user_roles(user: User, roles: Iterable[Role]) -> None:
    """Make the user's user_roles rows match `roles`, touching only the rows that change."""
    wanted = {role.id: role for role in roles}
    for link in list(user.user_roles):
        if link.role_id not in wanted:
            user.user_roles.remove(link)  # delete-orphan removes the row
    held = {link.role_id for link in user.user_roles}
    for role_id, role in wanted.items():
        if role_id not in held:
            user.user_roles.append(UserRole(role=role))


async def check_role(db: AsyncSession, user_id: int, role_name: str) -> bool:
    """True if the user holds the role (kept for modules that check roles by user id)."""
    held = await db.scalar(
        select(
            exists()
            .where(UserRole.user_id == user_id, UserRole.role_id == Role.id)
            .where(Role.name == role_name)
        )
    )
    return bool(held)


# ------------------------------------------------------------------ loading users


async def get_user_with_details(db: AsyncSession, user_id: int) -> User | None:
    """The user with roles, student profile and track assignments loaded.

    populate_existing refreshes an object already in this session (e.g. the one the auth
    dependency loaded without details). Call it only when there are no unsaved changes.
    """
    query = (
        select(User)
        .where(User.id == user_id)
        .options(*USER_DETAIL_OPTIONS)
        .execution_options(populate_existing=True)
    )
    return (await db.scalars(query)).first()


def new_user(**fields: object) -> User:
    """A new User whose student profile and track list start empty, so reading them before
    the first commit doesn't try to load them from the database."""
    user = User(**fields)
    user.student = None
    user.track_assignments = []
    return user


# ------------------------------------------------------------------ registration


async def register_student(db: AsyncSession, data: RegisterRequest, client: ClientInfo) -> User:
    if not settings.allow_student_self_registration:
        raise Forbidden("REGISTRATION_CLOSED", "Student registration is closed right now.")
    if await db.get(Department, data.department_id) is None:
        raise BadRequest("DEPARTMENT_NOT_FOUND", "Unknown department.")
    if data.academic_year_id is not None and await db.get(AcademicYear, data.academic_year_id) is None:
        raise BadRequest("ACADEMIC_YEAR_NOT_FOUND", "Unknown academic year.")

    user = new_user(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        phone=data.phone,
        password_hash=await security.hash_password(data.password),
    )
    user.student = Student(
        reg_num=data.reg_num,
        roll_number=data.roll_number,
        department_id=data.department_id,
        academic_year_id=data.academic_year_id,
        curr_sem=data.curr_sem,
    )
    set_user_roles(user, await get_roles(db, [RoleName.STUDENT]))
    db.add(user)
    await flush_or_conflict(db)  # a taken username/email/reg_num/roll_number becomes a 409 with its own code

    record(db, AuditAction.USER_REGISTERED, actor_id=user.id, target_id=user.id, ip=client.ip)
    await db.commit()
    return await get_user_with_details(db, user.id)  # type: ignore[return-value]


# ------------------------------------------------------------------ login


async def authenticate(db: AsyncSession, identifier: str, password: str, client: ClientInfo) -> IssuedTokens:
    """Check a username-or-email and password, apply the lockout rules, and issue tokens."""
    identifier = identifier.strip().lower()
    column = User.email if "@" in identifier else User.username
    # FOR UPDATE: two simultaneous logins to one account can't miscount failed attempts.
    user = (await db.scalars(select(User).where(column == identifier).with_for_update())).first()
    now = utcnow()

    if user is None or user.password_hash is None:
        await security.burn_password_check(password)
        logger.info("Failed login for unknown account %r from %s", identifier, client.ip)
        await db.rollback()
        raise Unauthorized("INVALID_CREDENTIALS", INVALID_CREDENTIALS)

    if user.locked_until is not None and user.locked_until > now:
        error = _account_locked(user.locked_until, now)
        await db.rollback()  # releases the row lock
        raise error

    is_valid, upgraded_hash = await security.verify_password(password, user.password_hash)
    if not is_valid:
        user.failed_login_count += 1
        record(db, AuditAction.LOGIN_FAILED, target_id=user.id, ip=client.ip)
        if user.failed_login_count >= settings.login_max_failed_attempts:
            user.failed_login_count = 0
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            record(db, AuditAction.ACCOUNT_LOCKED, target_id=user.id, ip=client.ip)
            error = _account_locked(user.locked_until, now)
            await db.commit()
            raise error
        await db.commit()
        raise Unauthorized("INVALID_CREDENTIALS", INVALID_CREDENTIALS)

    # Checked only after the password is right, so this doesn't reveal which accounts exist.
    if not user.is_active:
        await db.rollback()
        raise Forbidden("ACCOUNT_DISABLED", "This account has been deactivated. Please contact the administrator.")

    if upgraded_hash:
        user.password_hash = upgraded_hash
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    # Housekeeping: expired refresh tokens can never be used again.
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.expires_at < now))
    tokens = issue_tokens(db, user, client)
    record(db, AuditAction.LOGIN_SUCCEEDED, actor_id=user.id, target_id=user.id, ip=client.ip)
    await db.commit()
    return tokens


def _account_locked(locked_until: datetime, now: datetime) -> TooManyRequests:
    seconds = max(1, math.ceil((locked_until - now).total_seconds()))
    return TooManyRequests(
        "ACCOUNT_LOCKED",
        f"Too many failed login attempts. Try again in {math.ceil(seconds / 60)} minute(s).",
        headers={"Retry-After": str(seconds)},
    )


# ------------------------------------------------------------------ tokens


def issue_tokens(db: AsyncSession, user: User, client: ClientInfo, *, family_id: str | None = None) -> IssuedTokens:
    """Create an access token and a new refresh token (stored as a hash). The caller commits."""
    refresh_token = security.generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=security.hash_token(refresh_token),
            family_id=family_id or uuid.uuid4().hex,
            expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
            user_agent=client.user_agent[:255] if client.user_agent else None,
            ip_address=client.ip,
        )
    )
    access_token, expires_in = security.create_access_token(
        user_id=user.id, roles=user.role_names, token_version=user.token_version
    )
    return IssuedTokens(user=user, access_token=access_token, expires_in=expires_in, refresh_token=refresh_token)


async def rotate_refresh_token(db: AsyncSession, raw_token: str | None, client: ClientInfo) -> IssuedTokens:
    """Exchange a refresh token for a new one plus a new access token.

    Each refresh token works once. If a token that was already exchanged shows up again,
    someone may have copied it, so that whole login session is revoked and the user's access
    tokens stop working. The exception is a repeat within a few seconds while the session is
    still alive, which is normally two browser tabs refreshing at the same moment.
    """
    if not raw_token:
        raise Unauthorized("REFRESH_TOKEN_MISSING", "You are not logged in.")
    token = (
        await db.scalars(
            select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(raw_token)).with_for_update()
        )
    ).first()
    if token is None:
        raise Unauthorized("INVALID_REFRESH_TOKEN", SESSION_ENDED)

    now = utcnow()
    if token.revoked_at is not None and not await _is_parallel_refresh(db, token, now):
        await _revoke_family(db, token.family_id, RevokeReason.REUSE_DETECTED, now)
        owner = await db.get(User, token.user_id)
        if owner is not None:
            owner.token_version += 1  # also kill access tokens already handed out
        record(
            db,
            AuditAction.REFRESH_TOKEN_REUSED,
            target_id=token.user_id,
            details={"family_id": token.family_id},
            ip=client.ip,
        )
        await db.commit()
        raise Unauthorized("INVALID_REFRESH_TOKEN", SESSION_ENDED)

    if token.expires_at <= now:
        raise Unauthorized("REFRESH_TOKEN_EXPIRED", "Your session has expired. Please log in again.")

    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise Unauthorized("ACCOUNT_DISABLED", "This account has been deactivated.")

    if token.revoked_at is None:
        token.revoked_at = now
        token.revoked_reason = RevokeReason.ROTATED
    tokens = issue_tokens(db, user, client, family_id=token.family_id)
    await db.commit()
    return tokens


async def _is_parallel_refresh(db: AsyncSession, token: RefreshToken, now: datetime) -> bool:
    """True if the token was exchanged only seconds ago and its session hasn't been ended."""
    if token.revoked_reason != RevokeReason.ROTATED or token.revoked_at is None:
        return False
    if now - token.revoked_at > timedelta(seconds=settings.refresh_reuse_grace_seconds):
        return False
    session_alive = await db.scalar(
        select(exists().where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None)))
    )
    return bool(session_alive)


async def _revoke_family(db: AsyncSession, family_id: str, reason: RevokeReason, now: datetime) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason)
    )


async def invalidate_all_sessions(db: AsyncSession, user: User, reason: RevokeReason) -> None:
    """Log the user out everywhere: their access tokens stop working (token_version changes)
    and every refresh token is revoked. The caller commits."""
    user.token_version += 1
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason)
    )


# ------------------------------------------------------------------ logout


async def logout(db: AsyncSession, raw_token: str | None) -> None:
    """End the login session this refresh token belongs to (this browser only)."""
    if not raw_token:
        return
    token = (
        await db.scalars(select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(raw_token)))
    ).first()
    if token is not None:
        await _revoke_family(db, token.family_id, RevokeReason.LOGOUT, utcnow())
        await db.commit()


async def logout_everywhere(db: AsyncSession, user: User, client: ClientInfo) -> None:
    await invalidate_all_sessions(db, user, RevokeReason.LOGOUT_ALL)
    record(db, AuditAction.LOGOUT_ALL, actor_id=user.id, target_id=user.id, ip=client.ip)
    await db.commit()


# ------------------------------------------------------------------ own account


async def change_password(
    db: AsyncSession, user: User, current_password: str, new_password: str, client: ClientInfo
) -> IssuedTokens:
    """Change the password, end every other session, and return fresh tokens for this one."""
    is_valid, _ = await security.verify_password(current_password, user.password_hash)
    if not is_valid:
        raise BadRequest("INVALID_CURRENT_PASSWORD", "Your current password is incorrect.")
    user = await get_user_with_details(db, user.id)  # type: ignore[assignment]  # need user.student below
    forbidden = {value.lower() for value in (user.username, user.email) if value}
    if user.student is not None and user.student.reg_num:
        forbidden.add(user.student.reg_num.lower())
    if new_password.lower() in forbidden:
        raise BadRequest("WEAK_PASSWORD", "The password can't be your username, email or register number.")

    user.password_hash = await security.hash_password(new_password)
    user.must_change_password = False
    await invalidate_all_sessions(db, user, RevokeReason.PASSWORD_CHANGED)
    tokens = issue_tokens(db, user, client)
    record(db, AuditAction.PASSWORD_CHANGED, actor_id=user.id, target_id=user.id, ip=client.ip)
    await db.commit()
    return tokens


async def update_own_profile(db: AsyncSession, user: User, data: UpdateMeRequest, client: ClientInfo) -> User:
    if "phone" in data.model_fields_set and data.phone != user.phone:
        user.phone = data.phone
        record(
            db,
            AuditAction.PROFILE_UPDATED,
            actor_id=user.id,
            target_id=user.id,
            details={"fields": ["phone"]},
            ip=client.ip,
        )
        await db.commit()
    return await get_user_with_details(db, user.id)  # type: ignore[return-value]
