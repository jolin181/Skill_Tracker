"""
app/core/dependencies.py
------------------------
Shared FastAPI dependency functions used across all module routers.

Dict-returning dependencies (unchanged interface, used by the existing modules):
- `get_current_user()`  — the logged-in user as {"id": ..., "user": User, "roles": [...]}.
- `require_admin()`     — the same dict; the user must hold the "admin" role.
- `require_student()`   — the same dict; the user must hold the "student" role.

Typed dependencies (return the User model):
    CurrentUser              any logged-in user whose password is in order
    AuthenticatedUser        also lets through users who still must change a temporary password
                             (only /auth/me, /auth/change-password and /auth/logout-all use it)
    require_roles(...)       let through users holding at least one of the given roles
    AdminUser, StudentUser, DomainOwnerUser, DomainOwnerOrAdmin, StaffUser
                             ready-made role checks
    TrackManager             admins, or domain owners whose role is linked to the {track_id} in the URL
    managed_track_ids(user)  for list queries: the tracks a user may manage (None = all)

Roles always come from the database (user_roles joined to roles), never from the token, so
deactivating a user or changing their roles takes effect on their very next request.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import Forbidden, Unauthorized
from app.modules.auth.models import DOMAIN_OWNER_ROLES, STAFF_ROLES, RoleName
from app.modules.auth.service import ClientInfo
from app.modules.users.models import User

DbSession = Annotated[AsyncSession, Depends(get_db)]

# tokenUrl lets the "Authorize" button in Swagger UI (/docs) log in through /auth/login.
# auto_error=False so a missing token gets our standard error body instead of FastAPI's.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login", auto_error=False)


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


Client = Annotated[ClientInfo, Depends(get_client_info)]


# ── Who is calling? ───────────────────────────────────────────────────────────

async def get_authenticated_user(db: DbSession, token: Annotated[str | None, Depends(oauth2_scheme)]) -> User:
    """Check the Bearer token and load the user (with their roles) from the database."""
    if not token:
        raise Unauthorized("NOT_AUTHENTICATED", "You are not logged in.")
    try:
        payload = security.decode_access_token(token)
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("TOKEN_EXPIRED", "Your access token has expired.") from None
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise Unauthorized("INVALID_TOKEN", "Invalid access token.") from None

    user = await db.get(User, user_id)  # user_roles (and their roles) load in the same call
    if user is None:
        raise Unauthorized("INVALID_TOKEN", "Invalid access token.")
    if not user.is_active:
        raise Unauthorized("ACCOUNT_DISABLED", "This account has been deactivated.")
    if payload.get("ver") != user.token_version:
        raise Unauthorized("TOKEN_REVOKED", "This session has ended. Please log in again.")
    return user


async def get_active_user(user: Annotated[User, Depends(get_authenticated_user)]) -> User:
    """Like get_authenticated_user, but blocks accounts that must first replace a temporary password."""
    if user.must_change_password:
        raise Forbidden("PASSWORD_CHANGE_REQUIRED", "Please change your password before continuing.")
    return user


AuthenticatedUser = Annotated[User, Depends(get_authenticated_user)]
CurrentUser = Annotated[User, Depends(get_active_user)]


# ── What roles do they hold? ──────────────────────────────────────────────────

def require_roles(*roles: RoleName) -> Callable[[User], Awaitable[User]]:
    """Dependency that lets through only users holding at least one of the given roles.

    Admins are not let through automatically: list RoleName.ADMIN wherever admins should be allowed.
    """
    allowed = frozenset(roles)

    async def check_roles(user: CurrentUser) -> User:
        if allowed.isdisjoint(user.role_set):
            raise Forbidden("INSUFFICIENT_ROLE", "You don't have permission to do this.")
        return user

    return check_roles


AdminUser = Annotated[User, Depends(require_roles(RoleName.ADMIN))]
StudentUser = Annotated[User, Depends(require_roles(RoleName.STUDENT))]
DomainOwnerUser = Annotated[User, Depends(require_roles(*DOMAIN_OWNER_ROLES))]
DomainOwnerOrAdmin = Annotated[User, Depends(require_roles(*DOMAIN_OWNER_ROLES, RoleName.ADMIN))]
StaffUser = Annotated[User, Depends(require_roles(*STAFF_ROLES))]


# ── Dict-returning dependencies (interface used by the existing modules) ──────

def _as_dict(user: User) -> dict[str, Any]:
    return {"id": user.id, "user": user, "roles": user.role_names}


async def get_current_user(user: CurrentUser) -> dict[str, Any]:
    """The logged-in user as {"id": int, "user": User, "roles": [role names]}."""
    return _as_dict(user)


async def require_admin(user: AdminUser) -> dict[str, Any]:
    """Same dict as get_current_user; 403 unless the user holds the admin role."""
    return _as_dict(user)


async def require_student(user: StudentUser) -> dict[str, Any]:
    """Same dict as get_current_user; 403 unless the user holds the student role."""
    return _as_dict(user)


# ── Which tracks may they touch? ──────────────────────────────────────────────

def managed_track_ids(user: User) -> set[int] | None:
    """Tracks this user may manage: the tracks linked to their domain-owner roles.
    None means every track (admins). Needs no query: the roles are loaded with the user.

    For list endpoints:  ids = managed_track_ids(user)
                         if ids is not None: query = query.where(Track.id.in_(ids))
    """
    if user.is_admin:
        return None
    return set(user.owned_track_ids)


def can_manage_track(user: User, track_id: int) -> bool:
    return user.is_admin or track_id in user.owned_track_ids


async def require_track_manager(track_id: int, user: CurrentUser) -> User:
    """For routes with {track_id} in the path, e.g. POST /tracks/{track_id}/levels."""
    if not can_manage_track(user, track_id):
        raise Forbidden("NOT_TRACK_OWNER", "You can only manage the track of your domain-owner role.")
    return user


TrackManager = Annotated[User, Depends(require_track_manager)]


# ── CSRF check for cookie endpoints ───────────────────────────────────────────

def verify_request_origin(request: Request) -> None:
    """CSRF protection for the endpoints that use the refresh cookie (/auth/refresh, /auth/logout).

    Browsers attach an Origin header to POST requests. Only the frontend (ALLOWED_ORIGINS) and the
    API's own pages (Swagger UI) may use the cookie. Requests without an Origin header come from
    tools such as curl or Postman, which another website can't make on a user's behalf.
    """
    origin = request.headers.get("origin")
    if origin is None or origin in settings.allowed_origins:
        return
    if urlsplit(origin).netloc == request.headers.get("host"):
        return
    raise Forbidden("BAD_ORIGIN", "Requests from this origin are not allowed.")
