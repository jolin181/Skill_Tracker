"""
app/modules/auth/models.py
--------------------------
Roles and refresh tokens.

A user's roles are NOT a column on users. They are the rows of user_roles joined to roles:

    users.id → user_roles.user_id → user_roles.role_id → roles.id → roles.name

The six role names below are inserted into `roles` by the migration (and by
ensure_roles() for tests and the seed script).
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, UTCDateTime
from app.utils.time_utils import utcnow


class RoleName(StrEnum):
    ADMIN = "admin"
    STUDENT = "student"
    FULLSTACK_DOMAIN_OWNER = "fullstack_domain_owner"
    CYBER_DOMAIN_OWNER = "cyber_domain_owner"
    CLOUD_DEVOPS_DOMAIN_OWNER = "cloud_devops_domain_owner"
    ML_DOMAIN_OWNER = "ml_domain_owner"


DOMAIN_OWNER_ROLES = frozenset(
    {
        RoleName.FULLSTACK_DOMAIN_OWNER,
        RoleName.CYBER_DOMAIN_OWNER,
        RoleName.CLOUD_DEVOPS_DOMAIN_OWNER,
        RoleName.ML_DOMAIN_OWNER,
    }
)
# Every role except student. Staff accounts are created by an admin; students register themselves.
STAFF_ROLES = DOMAIN_OWNER_ROLES | {RoleName.ADMIN}


class Role(Base):
    """Lookup table: one row per role name.

    track_id ties a domain-owner role to its track (fullstack_domain_owner → the Full Stack
    track). Holders of that role can manage that track and no other. It is NULL for admin and
    student, and for a domain-owner role whose track hasn't been created yet (link it with
    PATCH /api/v1/roles/{id}). Each track belongs to at most one role.
    """

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("track_id", name="uq_roles_track_id"),
        CheckConstraint("track_id IS NULL OR name LIKE '%domain_owner'", name="ck_roles_domain_owner_only"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=True, unique=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id", ondelete="SET NULL"))

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class UserRole(Base):
    """Which roles each user holds (many-to-many between users and roles).

    The unique (user_id, role_id) pair makes "which roles does user X have?" an index lookup and
    stops the same role being given twice. The role_id index serves "who has role Y?".
    """

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_id_role_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=True, index=True)

    # Loaded in the same query as the user_roles rows, so reading user.role_names costs no extra query.
    role: Mapped[Role] = relationship(lazy="joined")


class RevokeReason(StrEnum):
    ROTATED = "rotated"  # swapped for a new token by /auth/refresh
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    REUSE_DETECTED = "reuse_detected"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    DEACTIVATED = "deactivated"
    ROLES_CHANGED = "roles_changed"


class RefreshToken(Base):
    """One row per refresh token handed out. Only a SHA-256 hash of the token is stored.

    Each login starts a new family_id. Every /auth/refresh revokes the token it was given and
    issues a new one in the same family, so a family is one login session on one browser.
    A token is revoked when revoked_at is set.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String)
    family_id: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_reason: Mapped[str | None] = mapped_column(String(30))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))
