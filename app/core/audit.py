"""
app/core/audit.py
-----------------
The audit_log table (as created by the initial migration) and the helpers that write to it.

Neither helper commits: the entry is saved by the caller's commit, so an action and its audit
entry are stored together or not at all.
"""

import logging
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UTCDateTime
from app.utils.time_utils import utcnow

logger = logging.getLogger(__name__)


class AuditLog(Base):
    """Who did what: logins, lockouts, admin changes, secret-code reveals."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String, nullable=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=True, default=utcnow)


class AuditAction(StrEnum):
    USER_REGISTERED = "user.registered"
    PROFILE_UPDATED = "user.profile_updated"
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    ACCOUNT_LOCKED = "auth.account_locked"
    REFRESH_TOKEN_REUSED = "auth.refresh_token_reused"
    LOGOUT_ALL = "auth.logout_all"
    PASSWORD_CHANGED = "auth.password_changed"
    USER_CREATED = "admin.user_created"
    USER_UPDATED = "admin.user_updated"
    STUDENT_PROFILE_UPDATED = "admin.student_profile_updated"
    USER_DEACTIVATED = "admin.user_deactivated"
    USER_ACTIVATED = "admin.user_activated"
    PASSWORD_RESET = "admin.password_reset"
    USER_UNLOCKED = "admin.user_unlocked"
    TRACK_ASSIGNED = "admin.track_assigned"
    TRACK_UNASSIGNED = "admin.track_unassigned"
    DEPARTMENT_CREATED = "admin.department_created"
    ROLE_TRACK_CHANGED = "admin.role_track_changed"


def record(
    db: AsyncSession,
    action: str,
    *,
    actor_id: int | None = None,
    target_id: int | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Add an audit entry to the current transaction (used by auth and users)."""
    db.add(
        AuditLog(
            action=str(action),
            actor_user_id=actor_id,
            target_user_id=target_id,
            details=details or {},
            ip_address=ip,
        )
    )


async def write_audit_log(
    session: AsyncSession,
    action: str,
    actor_user_id: int | None = None,
    target_user_id: int | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Add an audit entry and flush it (used by other modules, e.g. secret_code).
    The caller commits. Non-integer ids (e.g. UUIDs) are kept in `details` instead."""
    extra = dict(details or {})
    if actor_user_id is not None and not isinstance(actor_user_id, int):
        extra.setdefault("actor", str(actor_user_id))
        actor_user_id = None
    if target_user_id is not None and not isinstance(target_user_id, int):
        extra.setdefault("target", str(target_user_id))
        target_user_id = None
    logger.info("Audit: %s by %s on %s %s", action, actor_user_id, target_user_id, extra)
    record(session, action, actor_id=actor_user_id, target_id=target_user_id, details=extra)
    await session.flush()
